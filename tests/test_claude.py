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
        value["execution_mode"] = "this_mac"
        return value

    def test_discovery_reports_version_without_help_dump(self) -> None:
        capability = discover_claude()
        self.assertIn("2.1.test", capability.version or "")
        self.assertEqual(capability.auth_status, "authenticated")
        self.assertNotIn("help_text", capability.public_dict())

    def test_dry_run_never_sends_request(self) -> None:
        result = run_claude(self.paths, self.config(), trigger="server_cli", dry_run=True)
        self.assertFalse(result["real_request_sent"])

    def test_invocation_isolates_tools_settings_and_mcp(self) -> None:
        arguments = _build_args(discover_claude(), "haiku")
        self.assertIn("--no-session-persistence", arguments)
        self.assertIn("--tools", arguments)
        self.assertIn("--setting-sources", arguments)
        self.assertIn("--strict-mcp-config", arguments)

    def test_auto_model_uses_haiku_and_records_unverified_window(self) -> None:
        result = run_claude(self.paths, self.config(), trigger="server_cli", dry_run=False)
        self.assertTrue(result["real_request_sent"])
        self.assertEqual(result["selected_model"], "claude-haiku-test")
        self.assertFalse(result["usage_window_verification"]["verified"])

    def test_api_key_stops_real_execution(self) -> None:
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "not-logged"}):
            with self.assertRaises(AppError) as context:
                run_claude(self.paths, self.config(), trigger="server_cli", dry_run=False)
        self.assertEqual(context.exception.code, ErrorCode.API_KEY_DETECTED)


if __name__ == "__main__":
    unittest.main()
