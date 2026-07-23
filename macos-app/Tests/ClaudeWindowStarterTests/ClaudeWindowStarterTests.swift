import XCTest
@testable import ClaudeWindowStarter

final class ClaudeWindowStarterTests: XCTestCase {
    func testEnvelopeDecodesSnakeCaseContract() throws {
        let input = #"{"schema_version":1,"ok":true,"status":"success","error":null,"sanitized_message":null,"data":{"enabled":false}}"#
        let value = try JSONDecoder().decode(CommandEnvelope.self, from: Data(input.utf8))
        XCTAssertTrue(value.ok)
        XCTAssertEqual(value.schemaVersion, 1)
        XCTAssertEqual(value.status, "success")
    }

    func testExecutionTargetDefaultsToOracle() {
        XCTAssertEqual(ClientSettings().target, .oracle)
    }

    func testSettingsPersistWithoutCredentials() throws {
        let suite = "ClaudeWindowStarterTests-\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        var settings = ClientSettings()
        settings.host = "oracle.example"
        settings.repositoryURL = "git@github.com:owner/private.git"
        settings.protectedBranchConfirmed = true

        try SettingsStore.save(settings, defaults: defaults)

        XCTAssertEqual(SettingsStore.load(defaults: defaults), settings)
        XCTAssertNil(defaults.string(forKey: "telegram_token"))
        XCTAssertNil(defaults.string(forKey: "claude_oauth_token"))
    }
}
