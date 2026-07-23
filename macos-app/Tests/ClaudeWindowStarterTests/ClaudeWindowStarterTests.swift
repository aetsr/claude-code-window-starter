import XCTest
@testable import ClaudeWindowStarter

final class ClaudeWindowStarterTests: XCTestCase {
    func testEnvelopeDecodesV2SnakeCaseContract() throws {
        let input = #"{"schema_version":2,"ok":true,"status":"success","error":null,"sanitized_message":null,"data":{"enabled":false}}"#
        let value = try JSONDecoder().decode(CommandEnvelope.self, from: Data(input.utf8))
        XCTAssertTrue(value.ok)
        XCTAssertEqual(value.schemaVersion, 2)
        XCTAssertEqual(value.status, "success")
    }

    func testBackgroundModeDefaultsOff() {
        XCTAssertFalse(ClientSettings().backgroundEnabled)
        XCTAssertFalse(ClientSettings().enabled)
    }

    func testSettingsPersistWithoutCredentialsOrLegacyTargetFields() throws {
        let suite = "ClaudeWindowStarterTests-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        var settings = ClientSettings()
        settings.backgroundEnabled = true
        settings.telegramEnabled = true
        settings.telegramUserID = "100"

        try SettingsStore.save(settings, defaults: defaults)

        XCTAssertEqual(SettingsStore.load(defaults: defaults), settings)
        XCTAssertNil(defaults.string(forKey: "telegram_token"))
        XCTAssertNil(defaults.string(forKey: "claude_oauth_token"))
    }
}
