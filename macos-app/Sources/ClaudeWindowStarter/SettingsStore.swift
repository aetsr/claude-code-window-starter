import Foundation

enum SettingsStore {
    private static let key = "client-settings-v1"

    static func load(defaults: UserDefaults = .standard) -> ClientSettings {
        guard let data = defaults.data(forKey: key),
              let settings = try? JSONDecoder().decode(ClientSettings.self, from: data) else {
            return ClientSettings()
        }
        return settings
    }

    static func save(_ settings: ClientSettings, defaults: UserDefaults = .standard) throws {
        let data = try JSONEncoder().encode(settings)
        defaults.set(data, forKey: key)
    }

    static func reset(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: key)
    }
}
