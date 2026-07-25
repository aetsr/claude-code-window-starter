import Foundation
import IOKit.pwr_mgt
import Network
import Security

actor BackgroundAgent {
    private let mode: String
    private let base: URL
    private let configURL: URL
    private let stateURL: URL
    private let statusURL: URL
    private let command: [String]
    private var monitor: NWPathMonitor?
    private var online = false
    private var networkGeneration = 0
    private var assertion: IOPMAssertionID = 0
    private var runAssertion: IOPMAssertionID = 0
    private var processRunning = false
    private var lastOfflineSignal = Date.distantPast

    init(mode: String, command: [String] = []) {
        self.mode = mode
        self.command = command
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        self.base = appSupport.appending(path: "ClaudeWindowStarter")
        self.configURL = self.base.appending(path: "shared/config/config.json")
        self.stateURL = self.base.appending(path: "shared/state/state.json")
        self.statusURL = self.base.appending(path: "shared/runtime/background.json")
    }

    func run() async {
        if mode == "run" {
            await runProtectedCommand()
            return
        } else if mode == "telegram" {
            await runTelegramSupervisor()
            return
        }
        await runBackgroundSupervisor()
    }

    private func runProtectedCommand() async {
        guard !command.isEmpty else { return }
        let python = base.appending(path: "current/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { return }
        acquireRunAssertion()
        defer { releaseRunAssertion() }
        let process = Process()
        process.executableURL = python
        process.arguments = command
        process.environment = agentEnvironment()
        process.currentDirectoryURL = base.appending(path: "shared/runtime")
        process.standardInput = FileHandle.standardInput
        process.standardOutput = FileHandle.standardOutput
        process.standardError = FileHandle.standardError
        try? process.run()
        process.waitUntilExit()
    }

    private func runBackgroundSupervisor() async {
        let pathMonitor = NWPathMonitor()
        monitor = pathMonitor
        pathMonitor.pathUpdateHandler = { [weak self] path in
            Task { await self?.networkPathChanged(path.status == .satisfied) }
        }
        pathMonitor.start(queue: DispatchQueue(label: "com.openai.claude-window-starter.network"))
        defer { pathMonitor.cancel() }

        while !Task.isCancelled {
            let config = readConfig()
            let enabled = config["background_enabled"] as? Bool ?? false
            let automationEnabled = config["enabled"] as? Bool ?? false
            if enabled {
                acquireAssertion()
            } else {
                releaseAssertion()
            }
            writeStatus(enabled: enabled, automationEnabled: automationEnabled)
            if automationEnabled && online && !processRunning {
                let windowType = windowsDue(config: config)
                if !windowType.isEmpty {
                    await runAutomatic(windowType: windowType)
                }
            } else if automationEnabled && !online &&
                        Date().timeIntervalSince(lastOfflineSignal) >= 30 {
                lastOfflineSignal = Date()
                await signalConnectivity("offline")
            }
            // Re-read config frequently so turning the segment off releases the assertion promptly.
            try? await Task.sleep(for: .seconds(5))
        }
        releaseAssertion()
    }

    private func runAutomatic(windowType: String) async {
        processRunning = true
        acquireRunAssertion()
        defer {
            releaseRunAssertion()
            processRunning = false
        }
        let python = base.appending(path: "current/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { return }
        let process = Process()
        process.executableURL = python
        process.arguments = ["-m", "claude_starter", "--home", base.path, "--json", "run", "--window-type", windowType, "--trigger", "background"]
        process.environment = agentEnvironment()
        process.currentDirectoryURL = base.appending(path: "shared/runtime")
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        do { try process.run(); process.waitUntilExit() } catch { return }
    }

    private func runTelegramSupervisor() async {
        while !Task.isCancelled {
            let config = readConfig()
            let enabled = (config["telegram"] as? [String: Any])?["enabled"] as? Bool ?? false
            if enabled, let token = KeychainStore.load(account: "telegram_token") {
                await runTelegram(token: token)
            } else {
                try? await Task.sleep(for: .seconds(15))
            }
        }
    }

    private func runTelegram(token: String) async {
        let python = base.appending(path: "current/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { return }
        let process = Process()
        process.executableURL = python
        process.arguments = ["-m", "claude_starter", "--home", base.path, "--json", "telegram-bot", "--token-stdin"]
        process.environment = agentEnvironment()
        process.currentDirectoryURL = base.appending(path: "shared/runtime")
        let input = Pipe()
        process.standardInput = input
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            try input.fileHandleForWriting.write(contentsOf: Data(token.utf8))
            try input.fileHandleForWriting.close()
            process.waitUntilExit()
        } catch {
            try? input.fileHandleForWriting.close()
        }
        try? await Task.sleep(for: .seconds(5))
    }

    private func readConfig() -> [String: Any] {
        guard let data = try? Data(contentsOf: configURL),
              let object = try? JSONSerialization.jsonObject(with: data),
              let config = object as? [String: Any] else { return [:] }
        return config
    }

    private func readState() -> [String: Any] {
        guard let data = try? Data(contentsOf: stateURL),
              let object = try? JSONSerialization.jsonObject(with: data),
              let state = object as? [String: Any] else { return [:] }
        return state
    }

    private func parseISO8601(_ value: Any?) -> Date? {
        guard let text = value as? String else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let parsed = formatter.date(from: text) {
            return parsed
        }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: text)
    }

    private func windowsDue(config: [String: Any]) -> String {
        let state = readState()
        var duWindow = ""

        // Check five_hour window
        if let windows = config["windows"] as? [String: Any],
           let fiveHour = windows["five_hour"] as? [String: Any],
           let enabled = fiveHour["enabled"] as? Bool,
           enabled {
            if let nextRun = parseISO8601(state["five_hour_next_run_at"]) {
                if Date() >= nextRun {
                    duWindow = "five_hour"
                }
            }
        }

        // Check weekly window (takes precedence, but both will be marked triggered on success)
        if let windows = config["windows"] as? [String: Any],
           let weekly = windows["weekly"] as? [String: Any],
           let enabled = weekly["enabled"] as? Bool,
           enabled {
            if let nextRun = parseISO8601(state["weekly_next_run_at"]) {
                if Date() >= nextRun {
                    duWindow = "weekly"
                }
            }
        }

        return duWindow
    }

    private func networkPathChanged(_ value: Bool) async {
        networkGeneration += 1
        let generation = networkGeneration
        if !value {
            online = false
            await signalConnectivity("offline")
            writeStatus(enabled: readConfig()["background_enabled"] as? Bool ?? false,
                        automationEnabled: readConfig()["enabled"] as? Bool ?? false)
            return
        }
        Task {
            try? await Task.sleep(for: .seconds(5))
            confirmNetwork(generation: generation)
        }
    }

    private func confirmNetwork(generation: Int) {
        guard generation == networkGeneration else { return }
        online = true
        Task { await self.signalConnectivity("online") }
        writeStatus(enabled: readConfig()["background_enabled"] as? Bool ?? false,
                    automationEnabled: readConfig()["enabled"] as? Bool ?? false)
    }

    private func signalConnectivity(_ state: String) async {
        let python = base.appending(path: "current/.venv/bin/python")
        guard FileManager.default.isExecutableFile(atPath: python.path) else { return }
        let process = Process()
        process.executableURL = python
        process.arguments = [
            "-m", "claude_starter", "--home", base.path, "--json",
            "schedule", "--network-state", state,
        ]
        process.environment = agentEnvironment()
        process.currentDirectoryURL = base.appending(path: "shared/runtime")
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return
        }
    }

    private func writeStatus(enabled: Bool, automationEnabled: Bool) {
        let payload: [String: Any] = [
            "enabled": enabled,
            "automation_enabled": automationEnabled,
            "network_online": online,
            "power_assertion": assertion != 0 || runAssertion != 0,
            "checked_at": ISO8601DateFormatter().string(from: Date()),
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]) else { return }
        let directory = statusURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let temporary = directory.appending(path: ".background-\(UUID().uuidString).tmp")
        do {
            try data.write(to: temporary, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: temporary.path)
            if FileManager.default.fileExists(atPath: statusURL.path) {
                _ = try FileManager.default.replaceItemAt(statusURL, withItemAt: temporary, backupItemName: nil, options: .usingNewMetadataOnly)
            } else {
                try FileManager.default.moveItem(at: temporary, to: statusURL)
            }
        } catch {
            try? FileManager.default.removeItem(at: temporary)
        }
    }

    private func agentEnvironment() -> [String: String] {
        let userHome = FileManager.default.homeDirectoryForCurrentUser.path
        let processEnv = ProcessInfo.processInfo.environment
        var env: [String: String] = [
            "HOME": userHome,
            "PATH": "\(userHome)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "en_US.UTF-8",
            "TMPDIR": processEnv["TMPDIR"] ?? FileManager.default.temporaryDirectory.path,
        ]
        if let user = processEnv["USER"] { env["USER"] = user }
        if let logname = processEnv["LOGNAME"] { env["LOGNAME"] = logname }
        if let shell = processEnv["SHELL"] { env["SHELL"] = shell }
        return env
    }

    private func acquireAssertion() {
        guard assertion == 0 else { return }
        let reason = "Claude Window Starter background automation"
        // PreventSystemSleep keeps the system awake even with lid closed on AC power.
        let result = IOPMAssertionCreateWithName(
            kIOPMAssertionTypePreventSystemSleep as CFString,
            IOPMAssertionLevel(kIOPMAssertionLevelOn),
            reason as CFString,
            &assertion
        )
        if result != kIOReturnSuccess { assertion = 0 }
    }

    private func releaseAssertion() {
        guard assertion != 0 else { return }
        IOPMAssertionRelease(assertion)
        assertion = 0
    }

    private func acquireRunAssertion() {
        guard runAssertion == 0 else { return }
        let reason = "Claude Window Starter active Claude request"
        let result = IOPMAssertionCreateWithName(
            kIOPMAssertionTypePreventUserIdleSystemSleep as CFString,
            IOPMAssertionLevel(kIOPMAssertionLevelOn),
            reason as CFString,
            &runAssertion
        )
        if result != kIOReturnSuccess { runAssertion = 0 }
    }

    private func releaseRunAssertion() {
        guard runAssertion != 0 else { return }
        IOPMAssertionRelease(runAssertion)
        runAssertion = 0
    }
}

enum KeychainStore {
    static func load(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.openai.claude-window-starter",
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data,
              let value = String(data: data, encoding: .utf8),
              !value.isEmpty else { return nil }
        return value
    }
}
