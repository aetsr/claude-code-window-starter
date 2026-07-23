import Foundation

struct BackendClient {
    private let runner = ProcessRunner()
    private let serviceHome = "/var/lib/claude-starter/.local/share/claude-window-starter"

    func command(settings: ClientSettings, arguments: [String], stdin: Data? = nil) async throws -> CommandEnvelope {
        let result: ProcessResult
        if settings.target == .oracle {
            result = try await remote(settings: settings, arguments: arguments, stdin: stdin)
        } else {
            result = try await local(arguments: arguments, stdin: stdin)
        }
        let candidate = result.stdout.isEmpty ? result.stderr : result.stdout
        guard let envelope = try? JSONDecoder().decode(CommandEnvelope.self, from: candidate) else {
            throw ProcessRunnerError.invalidOutput
        }
        if !envelope.ok {
            throw ProcessRunnerError.nonZero(result.status, envelope.error?.message ?? "Backend error")
        }
        return envelope
    }

    func applyConfig(settings: ClientSettings, data: Data) async throws -> CommandEnvelope {
        if settings.target == .oracle {
            let remoteCommand = "sudo -n -u claude-starter env XDG_RUNTIME_DIR=/run/user/$(id -u claude-starter) CLAUDE_STARTER_HOME=\(serviceHome) \(serviceHome)/current/scripts/apply-config-stdin.sh"
            let result = try await ssh(settings: settings, remoteCommand: remoteCommand, stdin: data)
            let candidate = result.stdout.isEmpty ? result.stderr : result.stdout
            guard let envelope = try? JSONDecoder().decode(CommandEnvelope.self, from: candidate) else {
                throw ProcessRunnerError.invalidOutput
            }
            return envelope
        }
        let result = try await command(settings: settings, arguments: ["config", "patch-stdin"], stdin: data)
        _ = try await command(settings: settings, arguments: ["schedule", "--apply-launchd"])
        return result
    }

    func storeCredential(settings: ClientSettings, name: String, secret: String) async throws {
        guard ["claude_oauth_token", "telegram_token"].contains(name) else {
            throw ProcessRunnerError.launch("Unsupported credential")
        }
        if settings.target == .thisMac {
            let result = try await command(
                settings: settings,
                arguments: ["credential", "store", name],
                stdin: Data((secret + "\n").utf8)
            )
            guard result.ok else {
                throw ProcessRunnerError.invalidOutput
            }
            return
        }
        let command = "sudo -n -u claude-starter env CLAUDE_STARTER_HOME=\(serviceHome) \(serviceHome)/current/scripts/store-credential.sh \(name)"
        let result = try await ssh(settings: settings, remoteCommand: command, stdin: Data((secret + "\n").utf8))
        guard result.status == 0 else {
            throw ProcessRunnerError.nonZero(result.status, String(decoding: result.stderr, as: UTF8.self))
        }
    }

    func configureGitDeployKey(settings: ClientSettings, expectedFingerprint: String) async throws -> String {
        guard !expectedFingerprint.isEmpty else {
            throw ProcessRunnerError.launch("GitHub's independently verified ED25519 fingerprint is required.")
        }
        let command = "sudo -n -u claude-starter env CLAUDE_STARTER_HOME=\(serviceHome) \(serviceHome)/current/scripts/configure-git-deploy-key.sh --stdin"
        let result = try await ssh(
            settings: settings,
            remoteCommand: command,
            stdin: Data((expectedFingerprint + "\n").utf8)
        )
        guard result.status == 0 else {
            throw ProcessRunnerError.nonZero(result.status, String(decoding: result.stderr, as: UTF8.self))
        }
        return String(decoding: result.stdout, as: UTF8.self)
    }

    func testSSH(settings: ClientSettings) async throws -> String {
        let result = try await ssh(settings: settings, remoteCommand: "printf connected", stdin: nil)
        guard result.status == 0 else {
            throw ProcessRunnerError.nonZero(result.status, String(decoding: result.stderr, as: UTF8.self))
        }
        return String(decoding: result.stdout, as: UTF8.self)
    }

    func scanHostKey(settings: ClientSettings) async throws -> ScannedHostKey {
        guard !settings.host.isEmpty else { throw ProcessRunnerError.launch("Host is required.") }
        let scan = try await runner.run(
            executable: URL(filePath: "/usr/bin/ssh-keyscan"),
            arguments: ["-p", String(settings.port), "-t", "ed25519", settings.host]
        )
        guard scan.status == 0, !scan.stdout.isEmpty else {
            throw ProcessRunnerError.nonZero(scan.status, "Unable to scan the server host key")
        }
        let temporary = FileManager.default.temporaryDirectory.appending(path: UUID().uuidString)
        try scan.stdout.write(to: temporary, options: .atomic)
        defer { try? FileManager.default.removeItem(at: temporary) }
        let fingerprint = try await runner.run(
            executable: URL(filePath: "/usr/bin/ssh-keygen"),
            arguments: ["-lf", temporary.path, "-E", "sha256"]
        )
        guard fingerprint.status == 0 else {
            throw ProcessRunnerError.nonZero(fingerprint.status, "Unable to fingerprint the host key")
        }
        return ScannedHostKey(
            fingerprint: String(decoding: fingerprint.stdout, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines),
            knownHostsLine: String(decoding: scan.stdout, as: UTF8.self)
        )
    }

    func trustHostKey(settings: ClientSettings, key: ScannedHostKey) throws {
        let path = URL(filePath: settings.knownHostsPath)
        try FileManager.default.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data(key.knownHostsLine.utf8).write(to: path, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: path.path)
    }

    private func local(arguments: [String], stdin: Data?) async throws -> ProcessResult {
        let home = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appending(path: "ClaudeWindowStarter")
        let python = home.appending(path: "current/.venv/bin/python")
        let userHome = FileManager.default.homeDirectoryForCurrentUser.path
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = [
            "\(userHome)/.local/bin",
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ].joined(separator: ":")
        return try await runner.run(
            executable: python,
            arguments: ["-m", "claude_starter", "--home", home.path, "--json"] + arguments,
            stdin: stdin,
            environment: environment
        )
    }

    private func remote(settings: ClientSettings, arguments: [String], stdin: Data?) async throws -> ProcessResult {
        let allowed = Set(["status", "diagnose", "health", "run", "update", "releases", "rollback", "version", "telegram-test", "logs", "service", "schedule"])
        guard let first = arguments.first, allowed.contains(first) else {
            throw ProcessRunnerError.launch("Unsupported remote command")
        }
        let fixedArguments = arguments.map(shellQuote).joined(separator: " ")
        let command = "sudo -n -u claude-starter env XDG_RUNTIME_DIR=/run/user/$(id -u claude-starter) CLAUDE_STARTER_HOME=\(serviceHome) \(serviceHome)/current/.venv/bin/python -m claude_starter --home \(serviceHome) --json \(fixedArguments)"
        return try await ssh(settings: settings, remoteCommand: command, stdin: stdin)
    }

    private func ssh(settings: ClientSettings, remoteCommand: String, stdin: Data?) async throws -> ProcessResult {
        guard !settings.host.isEmpty, !settings.keyPath.isEmpty else {
            throw ProcessRunnerError.launch("SSH host and key path are required.")
        }
        let args = [
            "-p", String(settings.port),
            "-i", settings.keyPath,
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "ConnectTimeout=15",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=2",
            "-o", "StrictHostKeyChecking=yes",
            "-o", "UserKnownHostsFile=\(settings.knownHostsPath)",
            "\(settings.user)@\(settings.host)",
            remoteCommand
        ]
        return try await runner.run(executable: URL(filePath: "/usr/bin/ssh"), arguments: args, stdin: stdin)
    }

    private func shellQuote(_ value: String) -> String {
        // Only fixed backend arguments reach this method. Quoting prevents an accidental future expansion.
        "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

struct ScannedHostKey: Sendable {
    let fingerprint: String
    let knownHostsLine: String
}
