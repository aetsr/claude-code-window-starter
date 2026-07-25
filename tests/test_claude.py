from __future__ import annotations

import json
import os
import stat
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
elif "--model" in sys.argv and sys.argv[sys.argv.index("--model") + 1] == "limit-error":
    print(json.dumps({{
        "type": "result",
        "is_error": True,
        "result": "You've hit your limit · resets 11:10pm (Europe/Istanbul)"
    }}))
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

    def test_clean_environment_passes_through_user_and_logname(self) -> None:
        config = self.config()
        with mock.patch.dict(os.environ, {"USER": "testuser", "LOGNAME": "testuser", "TMPDIR": "/tmp/test"}):
            env = _clean_environment(self.paths, config)
        self.assertEqual(env.get("USER"), "testuser")
        self.assertEqual(env.get("LOGNAME"), "testuser")
        self.assertEqual(env.get("TMPDIR"), "/tmp/test")
        self.assertEqual(env.get("CLAUDE_CODE_SKIP_PROMPT_HISTORY"), "1")

    def test_clean_environment_excludes_prohibited_keys(self) -> None:
        config = self.config()
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test", "ANTHROPIC_AUTH_TOKEN": "tok"}):
            env = _clean_environment(self.paths, config)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)

    def test_hit_your_limit_classified_as_rate_limit(self) -> None:
        """Claude CLI 'hit your limit' mesajı RATE_OR_USAGE_LIMIT olarak sınıflanmalı."""
        config = self.config()
        config["model"] = "limit-error"
        with self.assertRaises(AppError) as context:
            run_claude(self.paths, config, trigger="macos_ui", dry_run=False)
        self.assertEqual(context.exception.code, ErrorCode.RATE_OR_USAGE_LIMIT)

    def test_is_error_json_with_limit_message_classified_correctly(self) -> None:
        """returncode=1 + is_error:true + result='hit your limit' olan JSON doğru sınıflanmalı."""
        from claude_starter.claude import _classify_failure

        capabilities = discover_claude()
        error = _classify_failure(
            "",
            '{"type":"result","is_error":true,"result":"You\'ve hit your limit · resets 11:10pm"}',
            1,
            capabilities,
        )
        self.assertEqual(error.code, ErrorCode.RATE_OR_USAGE_LIMIT)

    def test_various_limit_phrases_classified_as_rate_limit(self) -> None:
        """Çeşitli limit mesajları tanınmalı."""
        from claude_starter.claude import _classify_failure

        capabilities = discover_claude()
        limit_phrases = [
            "you've hit your limit",
            "daily limit exceeded",
            "usage cap reached",
            "hit the limit",
        ]
        for phrase in limit_phrases:
            with self.subTest(phrase=phrase):
                error = _classify_failure("", phrase, 1, capabilities)
                self.assertEqual(error.code, ErrorCode.RATE_OR_USAGE_LIMIT, f"Failed for: {phrase}")


    def test_manual_trigger_respects_window_when_automation_enabled(self) -> None:
        """Manual trigger should respect 5-hour window if automation enabled."""
        config = self.config()
        config["enabled"] = True
        config["model"] = "sonnet"
        # Run once to establish next_window_run_at in the future
        run_claude(self.paths, config, trigger="macos_ui", dry_run=False)
        state = json.loads(self.paths.state_file.read_text())
        next_window_iso = state["next_window_run_at"]
        # Try to run again immediately (should fail WINDOW_NOT_DUE)
        with self.assertRaises(AppError) as context:
            run_claude(self.paths, config, trigger="macos_ui", dry_run=False)
        self.assertEqual(context.exception.code, ErrorCode.WINDOW_NOT_DUE)

    def test_manual_trigger_ignores_window_when_automation_disabled(self) -> None:
        """Manual trigger should run anytime if automation is disabled."""
        config = self.config()
        config["enabled"] = False
        config["model"] = "sonnet"
        # First run
        result1 = run_claude(self.paths, config, trigger="macos_ui", dry_run=False)
        self.assertTrue(result1["real_request_sent"])
        # Immediate second run (should work because automation disabled)
        result2 = run_claude(self.paths, config, trigger="macos_ui", dry_run=False)
        self.assertTrue(result2["real_request_sent"])

    def test_rate_limit_error_updates_next_window(self) -> None:
        """Rate-limit error should update next_window_run_at even on manual trigger."""
        from claude_starter.cli import execute
        from claude_starter.io_utils import read_json
        import argparse

        config = self.config()
        config["enabled"] = True
        config["model"] = "limit-error"
        from claude_starter.config import save_config

        save_config(self.paths, config)
        state_before = read_json(self.paths.state_file, {})
        next_before = state_before.get("next_window_run_at")
        # Simulate CLI: run --manual --trigger macos_ui
        args = argparse.Namespace(
            command="run",
            manual=True,
            automatic=False,
            dry_run=False,
            trigger="macos_ui",
        )
        with self.assertRaises(AppError) as context:
            execute(args, self.paths)
        self.assertEqual(context.exception.code, ErrorCode.RATE_OR_USAGE_LIMIT)
        state_after = read_json(self.paths.state_file, {})
        next_after = state_after.get("next_window_run_at")
        # next_window_run_at should be updated to future time (5 hours from now)
        self.assertIsNotNone(next_after)
        self.assertNotEqual(next_after, next_before)


if __name__ == "__main__":
    unittest.main()
