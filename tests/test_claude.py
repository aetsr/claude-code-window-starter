from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter.claude import _build_args, _clean_environment, discover_claude, run_claude
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
        "--mcp-config --strict-mcp-config"
    )
elif "auth" in sys.argv:
    print(json.dumps({{"authenticated": True, "method": "oauth"}}))
elif "--model" in sys.argv and sys.argv[sys.argv.index("--model") + 1] == "haiku":
    print(json.dumps({{
        "result": "OK",
        "model": "claude-haiku-test",
        "usage": {{"input_tokens": 1}},
    }}))
elif "--model" in sys.argv and sys.argv[sys.argv.index("--model") + 1] == "timeout":
    time.sleep(2)
    sys.exit(1)
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

    def test_discovery_parses_logged_out_json_even_when_cli_exits_one(self) -> None:
        responses = [
            subprocess.CompletedProcess([], 0, "2.1.test", ""),
            subprocess.CompletedProcess([], 0, "--no-chrome", ""),
            subprocess.CompletedProcess(
                [],
                1,
                '{"loggedIn": false, "authMethod": "none"}',
                "",
            ),
            subprocess.CompletedProcess([], 0, "auth login help", ""),
        ]
        with mock.patch("claude_starter.claude._run_small", side_effect=responses):
            capability = discover_claude()
        self.assertEqual(capability.auth_status, "not_authenticated")
        self.assertEqual(capability.auth_method, "none")

    def test_dry_run_never_sends_request(self) -> None:
        result = run_claude(self.paths, self.config(), trigger="macos_ui", dry_run=True)
        self.assertFalse(result["real_request_sent"])

    def test_dry_run_with_window_type(self) -> None:
        result = run_claude(
            self.paths, self.config(), trigger="automatic", window_type="five_hour", dry_run=True
        )
        self.assertFalse(result["real_request_sent"])

    def test_invocation_isolates_tools_settings_and_mcp(self) -> None:
        arguments = _build_args(discover_claude(), "haiku")
        self.assertIn("--no-session-persistence", arguments)
        self.assertIn("--tools", arguments)
        self.assertIn("--strict-mcp-config", arguments)
        mcp_index = arguments.index("--mcp-config")
        self.assertEqual(arguments[mcp_index + 1], '{"mcpServers":{}}')

    def test_auto_model_uses_haiku_by_default(self) -> None:
        result = run_claude(self.paths, self.config(), trigger="macos_ui", dry_run=False)
        self.assertTrue(result["real_request_sent"])
        self.assertEqual(result["selected_model"], "claude-haiku-test")

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

    def test_clean_environment_passes_through_user_and_logname(self) -> None:
        config = self.config()
        test_temp = str(Path(tempfile.gettempdir()) / "test")
        with mock.patch.dict(
            os.environ, {"USER": "testuser", "LOGNAME": "testuser", "TMPDIR": test_temp}
        ):
            env = _clean_environment(self.paths, config)
        self.assertEqual(env.get("USER"), "testuser")
        self.assertEqual(env.get("LOGNAME"), "testuser")
        self.assertEqual(env.get("TMPDIR"), test_temp)
        self.assertEqual(env.get("CLAUDE_CODE_SKIP_PROMPT_HISTORY"), "1")

    def test_clean_environment_excludes_prohibited_keys(self) -> None:
        config = self.config()
        with mock.patch.dict(
            os.environ, {"ANTHROPIC_API_KEY": "sk-test", "ANTHROPIC_AUTH_TOKEN": "tok"}
        ):
            env = _clean_environment(self.paths, config)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)

    def test_window_type_parameter_accepted(self) -> None:
        config = self.config()
        result = run_claude(
            self.paths, config, trigger="automatic", window_type="five_hour", dry_run=True
        )
        self.assertFalse(result["real_request_sent"])

    def test_result_includes_response_and_model(self) -> None:
        result = run_claude(self.paths, self.config(), trigger="macos_ui", dry_run=False)
        self.assertIn("response", result)
        self.assertIn("selected_model", result)
        self.assertIn("duration_seconds", result)
        self.assertEqual(result["response"], "OK")

    def test_result_does_not_include_rate_limits(self) -> None:
        result = run_claude(self.paths, self.config(), trigger="macos_ui", dry_run=False)
        self.assertNotIn("rate_limits", result)
        self.assertNotIn("usage_window_verification", result)
        self.assertNotIn("usage_window", result)


if __name__ == "__main__":
    unittest.main()
