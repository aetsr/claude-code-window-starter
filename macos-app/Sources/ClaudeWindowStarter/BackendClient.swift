import Foundation

struct BackendClient {
    private let runner = ProcessRunner()

    func command(arguments: [String], stdin: Data? = nil) async throws -> CommandEnvelope {
        let result = try await local(arguments: arguments, stdin: stdin)
        let candidate = result.stdout.isEmpty ? result.stderr : result.stdout
        guard let envelope = try? JSONDecoder().decode(CommandEnvelope.self, from: candidate) else {
            throw ProcessRunnerError.invalidOutput
        }
        if !envelope.ok {
            throw ProcessRunnerError.nonZero(result.status, envelope.error?.message ?? "Backend error")
        }
        return envelope
    }

    func applyConfig(data: Data) async throws -> CommandEnvelope {
        try await command(arguments: ["config", "patch-stdin"], stdin: data)
    }

    func telegramTest() async throws -> CommandEnvelope {
        guard let token = KeychainStore.load(account: "telegram_token") else {
            throw ProcessRunnerError.launch("Telegram token is not configured in Keychain.")
        }
        return try await command(arguments: ["telegram-test", "--token-stdin"], stdin: Data(token.utf8))
    }

    func telegramPair(code: String) async throws -> CommandEnvelope {
        guard let token = KeychainStore.load(account: "telegram_token") else {
            throw ProcessRunnerError.launch("Telegram token is not configured in Keychain.")
        }
        return try await command(
            arguments: ["telegram-pair", "--code", code, "--token-stdin"],
            stdin: Data(token.utf8)
        )
    }

    private func local(arguments: [String], stdin: Data?) async throws -> ProcessResult {
        let home = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appending(path: "ClaudeWindowStarter")
        let python = home.appending(path: "current/.venv/bin/python")
        let userHome = FileManager.default.homeDirectoryForCurrentUser.path
        let processEnv = ProcessInfo.processInfo.environment
        var environment: [String: String] = [
            "HOME": userHome,
            "PATH": "\(userHome)/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "en_US.UTF-8",
            "TMPDIR": processEnv["TMPDIR"] ?? FileManager.default.temporaryDirectory.path,
        ]
        if let user = processEnv["USER"] { environment["USER"] = user }
        if let logname = processEnv["LOGNAME"] { environment["LOGNAME"] = logname }
        if let shell = processEnv["SHELL"] { environment["SHELL"] = shell }
        let helper = Bundle.main.bundleURL
            .appending(path: "Contents/Helpers/ClaudeWindowStarterAgent")
        let useProtectedRunner = arguments.first == "run" && FileManager.default.isExecutableFile(atPath: helper.path)
        let executable = useProtectedRunner ? helper : python
        let command = useProtectedRunner
            ? ["run", "-m", "claude_starter", "--home", home.path, "--json"] + arguments
            : ["-m", "claude_starter", "--home", home.path, "--json"] + arguments
        return try await runner.run(
            executable: executable,
            arguments: command,
            stdin: stdin,
            environment: environment
        )
    }
}
