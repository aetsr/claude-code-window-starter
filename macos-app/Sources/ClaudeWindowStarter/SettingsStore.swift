import Foundation

enum SettingsStore {
    private static let key = "client-settings-v2"
    private static let legacyKey = "client-settings-v1"

    static func load(defaults: UserDefaults = .standard) -> ClientSettings {
        let decoder = JSONDecoder()
        for key in [Self.key, Self.legacyKey] {
            if let data = defaults.data(forKey: key), let settings = try? decoder.decode(ClientSettings.self, from: data) {
                return settings
            }
        }
        return ClientSettings()
    }

    static func save(_ settings: ClientSettings, defaults: UserDefaults = .standard) throws {
        defaults.set(try JSONEncoder().encode(settings), forKey: key)
    }

    static func reset(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: key)
        defaults.removeObject(forKey: legacyKey)
    }
}
