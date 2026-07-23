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
}
