from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter.claude import _build_args, discover_claude, run_claude
from claude_starter.config import DEFAULT_CONFIG
from claude_starter.errors import AppError, ErrorCode
from claude_starter.paths import AppPaths

FAKE = """#!{python}
import json, sys, time
if "--version" in sys.argv:
    print("2.1.test (Claude Code)")
elif "--help" in sys.argv:
    print(
        "--output-format --model --no-session-persistence --no-chrome "
        "--disable-slash-commands --permission-mode dontAsk --tools "
        "--setting-sources --mcp-config --strict-mcp-config"
    )
elif "auth" in sys.argv:
    print(json.dumps({{"authenticated": True, "method": "oauth"}}))
elif "--model" in sys.argv and sys.argv[sys.argv.index("--model") + 1] == "sonnet":
    print(json.dumps({{
        "result": "OK",
        "model": "claude-sonnet-test",
        "rate_limits": {{
            "five_hour": {{"used_percentage": 1.5, "resets_at": 2000000000}}
        }},
    }}))
elif "--model" in sys.argv and sys.argv[sys.argv.index("--model") + 1] == "haiku":
    print(json.dumps({{
        "result": "OK",
        "model": "claude-haiku-test",
        "usage": {{"input_tokens": 1}},
    }}))
else:
    print(json.dumps({{"result": "OK", "model": "default-test"}}))
"""


class ClaudeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.paths = AppPaths(root / "app")
        self.paths.ensure()
        self.bin = root / "bin"
        self.bin.mkdir()
        executable = self.bin / "claude"
        executable.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        self.environment = mock.patch.dict(
            os.environ, {"PATH": f"{self.bin}:{os.environ.get('PATH', '')}"}, clear=False
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def config(self) -> dict[str, object]:
        value = json.loads(json.dumps(DEFAULT_CONFIG))
        return value

    def test_discovery_reports_version_without_help_dump(self) -> None:
        capability = discover_claude()
        self.assertIn("2.1.test", capability.version or "")
        self.assertEqual(capability.auth_status, "authenticated")
        self.assertNotIn("help_text", capability.public_dict())

    def test_dry_run_never_sends_request(self) -> None:
        result = run_claude(self.paths, self.config(), trigger="macos_ui", dry_run=True)
        self.assertFalse(result["real_request_sent"])

    def test_invocation_isolates_tools_settings_and_mcp(self) -> None:
        arguments = _build_args(discover_claude(), "haiku")
        self.assertIn("--no-session-persistence", arguments)
        self.assertIn("--tools", arguments)
        self.assertIn("--setting-sources", arguments)
        self.assertIn("--strict-mcp-config", arguments)
        mcp_index = arguments.index("--mcp-config")
        self.assertEqual(arguments[mcp_index + 1], '{"mcpServers":{}}')

    def test_auto_model_uses_haiku_and_records_unverified_window(self) -> None:
        result = run_claude(self.paths, self.config(), trigger="macos_ui", dry_run=False)
        self.assertTrue(result["real_request_sent"])
        self.assertEqual(result["selected_model"], "claude-haiku-test")
        self.assertFalse(result["usage_window_verification"]["verified"])

    def test_official_rate_limit_reset_is_persisted_and_verified(self) -> None:
        config = self.config()
        config["model"] = "sonnet"
        result = run_claude(self.paths, config, trigger="macos_ui", dry_run=False)
        self.assertTrue(result["usage_window_verification"]["verified"])
        state = json.loads(self.paths.state_file.read_text(encoding="utf-8"))
        self.assertEqual(
            state["usage_window"]["rate_limits"]["five_hour"]["resets_at"],
            2_000_000_000,
        )
        self.assertTrue(state["next_window_run_at"].startswith("2033-05-18T03:34:"))

    def test_background_trigger_starts_one_five_hour_window(self) -> None:
        config = self.config()
        config["enabled"] = True
        result = run_claude(self.paths, config, trigger="background", dry_run=False)
        self.assertTrue(result["real_request_sent"])
        with self.assertRaises(AppError) as context:
            run_claude(self.paths, config, trigger="background", dry_run=False)
        self.assertEqual(context.exception.code, ErrorCode.WINDOW_NOT_DUE)

    def test_api_key_stops_real_execution(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "not-logged"}):
            with self.assertRaises(AppError) as context:
                run_claude(self.paths, self.config(), trigger="macos_ui", dry_run=False)
        self.assertEqual(context.exception.code, ErrorCode.API_KEY_DETECTED)

    def test_explicit_unauthenticated_status_stops_before_request(self) -> None:
        capabilities = discover_claude()
        capabilities.auth_status = "not_authenticated"
        with mock.patch("claude_starter.claude.discover_claude", return_value=capabilities):
            with self.assertRaises(AppError) as context:
                run_claude(self.paths, self.config(), trigger="macos_ui", dry_run=False)
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_NOT_AUTHENTICATED)


if __name__ == "__main__":
    unittest.main()
