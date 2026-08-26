import XCTest
@testable import ClaudeWindowStarter
@testable import ClaudeWindowStarterAgent

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

    func testTelegramWorkerReceivesSupervisorPID() {
        let arguments = BackgroundAgent.telegramProcessArguments(
            basePath: "/tmp/ClaudeWindowStarter",
            supervisorPID: 4321
        )
        XCTAssertEqual(
            arguments,
            [
                "-m", "claude_starter", "--home", "/tmp/ClaudeWindowStarter", "--json",
                "telegram-bot", "--token-stdin", "--supervisor-pid", "4321",
            ]
        )
    }

    func testAdaptiveSettingsDefaults() {
        let settings = ClientSettings()
        XCTAssertEqual(settings.fiveHourMode, "adaptive")
        XCTAssertEqual(settings.busyStartLocal, "08:00")
        XCTAssertEqual(settings.busyEndLocal, "17:00")
        XCTAssertEqual(settings.activeWeekdays, [1, 2, 3, 4, 5])
        XCTAssertEqual(settings.fiveHourStrategy, "maximize_quota")
    }

    func testV4ScheduleEnvelopeDecodes() throws {
        let input = #"{"schema_version":4,"ok":true,"status":"success","error":null,"sanitized_message":null,"data":{"busy_period":{"start_local":"08:00","end_local":"17:00"},"today_actions":[{"scheduled_at":"2026-08-24T03:00:00+00:00"}],"next_action_at":"2026-08-24T08:03:00+00:00","confidence":"observed"}}"#
        let value = try JSONDecoder().decode(CommandEnvelope.self, from: Data(input.utf8))
        XCTAssertEqual(value.schemaVersion, 4)
        guard case .object(let data)? = value.data,
              case .string(let confidence)? = data["confidence"] else {
            return XCTFail("Adaptive schedule contract did not decode")
        }
        XCTAssertEqual(confidence, "observed")
    }

    func testBackgroundAgentDelegatesToScheduleTick() {
        XCTAssertEqual(
            BackgroundAgent.schedulerTickArguments(basePath: "/tmp/ClaudeWindowStarter"),
            [
                "-m", "claude_starter", "--home", "/tmp/ClaudeWindowStarter", "--json",
                "schedule", "--tick",
            ]
        )
    }
}
