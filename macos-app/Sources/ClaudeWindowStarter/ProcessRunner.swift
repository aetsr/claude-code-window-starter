import Foundation

enum ProcessRunnerError: LocalizedError {
    case launch(String)
    case nonZero(Int32, String)
    case invalidOutput

    var errorDescription: String? {
        switch self {
        case .launch(let message): return message
        case .nonZero(let code, let message): return "Command failed (\(code)): \(message)"
        case .invalidOutput: return "The backend returned invalid output."
        }
    }
}

struct ProcessResult: Sendable {
    let stdout: Data
    let stderr: Data
    let status: Int32
}

struct ProcessRunner {
    func run(
        executable: URL,
        arguments: [String],
        stdin: Data? = nil,
        environment: [String: String]? = nil
    ) async throws -> ProcessResult {
        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = executable
            process.arguments = arguments
            process.environment = environment
            let output = Pipe()
            let error = Pipe()
            process.standardOutput = output
            process.standardError = error
            if let stdin {
                let input = Pipe()
                process.standardInput = input
                try process.run()
                async let stdout = output.fileHandleForReading.readDataToEndOfFile()
                async let stderr = error.fileHandleForReading.readDataToEndOfFile()
                try input.fileHandleForWriting.write(contentsOf: stdin)
                try input.fileHandleForWriting.close()
                process.waitUntilExit()
                return await ProcessResult(
                    stdout: stdout,
                    stderr: stderr,
                    status: process.terminationStatus
                )
            } else {
                process.standardInput = FileHandle.nullDevice
                try process.run()
                async let stdout = output.fileHandleForReading.readDataToEndOfFile()
                async let stderr = error.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                return await ProcessResult(
                    stdout: stdout,
                    stderr: stderr,
                    status: process.terminationStatus
                )
            }
        }.value
    }
}
