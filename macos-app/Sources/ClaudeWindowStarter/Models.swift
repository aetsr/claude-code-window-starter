import Foundation

struct CommandEnvelope: Codable, Sendable {
    let schemaVersion: Int
    let ok: Bool
    let status: String
    let error: CommandError?
    let sanitizedMessage: String?
    let data: JSONValue?

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case ok, status, error, data
        case sanitizedMessage = "sanitized_message"
    }
}

struct CommandError: Codable, Sendable {
    let code: String
    let message: String
}

enum JSONValue: Codable, Sendable, CustomStringConvertible {
    case object([String: JSONValue])
    case array([JSONValue])
    case string(String)
    case number(Double)
    case bool(Bool)
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([String: JSONValue].self) { self = .object(value) }
        else { self = .array(try container.decode([JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }

    var description: String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        guard let data = try? encoder.encode(self) else { return "" }
        return String(decoding: data, as: UTF8.self)
    }
}

enum ExecutionTarget: String, CaseIterable, Identifiable {
    case oracle = "Oracle Server"
    case thisMac = "This Mac"
    var id: String { rawValue }
}

struct ClientSettings {
    var target: ExecutionTarget = .oracle
    var host = ""
    var port = 22
    var user = "ubuntu"
    var keyPath = ""
    var knownHostsPath: String = {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appending(path: "ClaudeWindowStarter/known_hosts").path
    }()
    var scheduleTime = "08:00"
    var timezone = "Europe/Istanbul"
    var model = "auto"
    var prompt = "Respond with OK."
    var timeout = 120
    var enabled = false
    var catchUp = true
    var repositoryURL = ""
    var branch = "main"
    var retainReleases = 5
    var telegramUserID = ""
    var telegramChatID = ""
    var notificationID = ""
    var telegramEnabled = false
    var notificationIsChannel = false
    var autoUpdate = false
    var autoApplyUpdates = false
}
