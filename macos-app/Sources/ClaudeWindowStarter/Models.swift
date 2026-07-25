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

struct ClientSettings: Codable, Equatable {
    var scheduleTime = "08:00"
    var timezone = "Europe/Istanbul"
    var model = "auto"
    var prompt = "Respond with OK."
    var timeout = 120
    var enabled = false
    var backgroundEnabled = false
    var catchUp = true
    var telegramUserID = ""
    var telegramChatID = ""
    var notificationID = ""
    var telegramEnabled = false
    var notificationIsChannel = false

    // Window configuration
    var fiveHourEnabled = true
    var fiveHourAnchorISO = ""
    var fiveHourIntervalMinutes = 303
    var weeklyEnabled = false
    var weeklyAnchorISO = ""
    var weeklyIntervalMinutes = 10080

    enum CodingKeys: String, CodingKey {
        case scheduleTime, timezone, model, prompt, timeout, enabled, backgroundEnabled, catchUp
        case telegramUserID, telegramChatID, notificationID, telegramEnabled, notificationIsChannel
        case fiveHourEnabled, fiveHourAnchorISO, fiveHourIntervalMinutes
        case weeklyEnabled, weeklyAnchorISO, weeklyIntervalMinutes
    }

    init() {}

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        scheduleTime = try values.decodeIfPresent(String.self, forKey: .scheduleTime) ?? scheduleTime
        timezone = try values.decodeIfPresent(String.self, forKey: .timezone) ?? timezone
        model = try values.decodeIfPresent(String.self, forKey: .model) ?? model
        prompt = try values.decodeIfPresent(String.self, forKey: .prompt) ?? prompt
        timeout = try values.decodeIfPresent(Int.self, forKey: .timeout) ?? timeout
        enabled = try values.decodeIfPresent(Bool.self, forKey: .enabled) ?? enabled
        backgroundEnabled = try values.decodeIfPresent(Bool.self, forKey: .backgroundEnabled) ?? backgroundEnabled
        catchUp = try values.decodeIfPresent(Bool.self, forKey: .catchUp) ?? catchUp
        telegramUserID = try values.decodeIfPresent(String.self, forKey: .telegramUserID) ?? telegramUserID
        telegramChatID = try values.decodeIfPresent(String.self, forKey: .telegramChatID) ?? telegramChatID
        notificationID = try values.decodeIfPresent(String.self, forKey: .notificationID) ?? notificationID
        telegramEnabled = try values.decodeIfPresent(Bool.self, forKey: .telegramEnabled) ?? telegramEnabled
        notificationIsChannel = try values.decodeIfPresent(Bool.self, forKey: .notificationIsChannel) ?? notificationIsChannel
        fiveHourEnabled = try values.decodeIfPresent(Bool.self, forKey: .fiveHourEnabled) ?? fiveHourEnabled
        fiveHourAnchorISO = try values.decodeIfPresent(String.self, forKey: .fiveHourAnchorISO) ?? fiveHourAnchorISO
        fiveHourIntervalMinutes = try values.decodeIfPresent(Int.self, forKey: .fiveHourIntervalMinutes) ?? fiveHourIntervalMinutes
        weeklyEnabled = try values.decodeIfPresent(Bool.self, forKey: .weeklyEnabled) ?? weeklyEnabled
        weeklyAnchorISO = try values.decodeIfPresent(String.self, forKey: .weeklyAnchorISO) ?? weeklyAnchorISO
        weeklyIntervalMinutes = try values.decodeIfPresent(Int.self, forKey: .weeklyIntervalMinutes) ?? weeklyIntervalMinutes
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(scheduleTime, forKey: .scheduleTime)
        try values.encode(timezone, forKey: .timezone)
        try values.encode(model, forKey: .model)
        try values.encode(prompt, forKey: .prompt)
        try values.encode(timeout, forKey: .timeout)
        try values.encode(enabled, forKey: .enabled)
        try values.encode(backgroundEnabled, forKey: .backgroundEnabled)
        try values.encode(catchUp, forKey: .catchUp)
        try values.encode(telegramUserID, forKey: .telegramUserID)
        try values.encode(telegramChatID, forKey: .telegramChatID)
        try values.encode(notificationID, forKey: .notificationID)
        try values.encode(telegramEnabled, forKey: .telegramEnabled)
        try values.encode(notificationIsChannel, forKey: .notificationIsChannel)
        try values.encode(fiveHourEnabled, forKey: .fiveHourEnabled)
        try values.encode(fiveHourAnchorISO, forKey: .fiveHourAnchorISO)
        try values.encode(fiveHourIntervalMinutes, forKey: .fiveHourIntervalMinutes)
        try values.encode(weeklyEnabled, forKey: .weeklyEnabled)
        try values.encode(weeklyAnchorISO, forKey: .weeklyAnchorISO)
        try values.encode(weeklyIntervalMinutes, forKey: .weeklyIntervalMinutes)
    }
}
