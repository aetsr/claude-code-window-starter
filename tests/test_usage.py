from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter.config import DEFAULT_CONFIG
from claude_starter.errors import AppError, ErrorCode
from claude_starter.paths import AppPaths
from claude_starter.usage import (
    create_usage_terminal_window,
    extract_usage_text,
    format_usage_message,
    query_usage,
    run_usage_session,
    strip_ansi,
    suffix_delta,
    usage_launch_command,
)


class UsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temporary.name))
        self.paths.ensure()
        self.config = json.loads(json.dumps(DEFAULT_CONFIG))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_strip_ansi_removes_escape_sequences(self) -> None:
        self.assertEqual(strip_ansi("\x1b[31mUsage: 52%\x1b[0m"), "Usage: 52%")

    def test_suffix_delta_prefers_overlap(self) -> None:
        self.assertEqual(suffix_delta(["line1", "line2", "line3"], ["line2", "line3", "/usage", "5h remaining 40%"]), ["/usage", "5h remaining 40%"])

    def test_extract_usage_text_ignores_tui_chrome(self) -> None:
        output = "Welcome to Claude Code\n/status /help\n/usage\nCurrent session 40% used\nResets in 2 hours\nCurrent week 82% used\n"
        self.assertEqual(extract_usage_text("", output), "Current session 40% used\nResets in 2 hours\nCurrent week 82% used")

    def test_format_usage_message_builds_bullets(self) -> None:
        message = format_usage_message("/usage\n5h remaining 40%\nWeekly remaining 82%\nReset in 2h")
        self.assertIn("Claude Kullanım Bilgisi", message)
        self.assertIn("• 5h remaining 40%", message)
        self.assertNotIn("/usage", message)

    def test_query_usage_uses_managed_terminal_window(self) -> None:
        capabilities = mock.Mock(executable="/usr/local/bin/claude", prohibited_credentials=[], auth_status="authenticated")
        with mock.patch("claude_starter.usage.discover_claude", return_value=capabilities), mock.patch("claude_starter.usage.run_usage_session", return_value="/usage\nCurrent session 40% used\nResets in 2 hours") as session:
            result = query_usage(self.paths, self.config)
        session.assert_called_once()
        self.assertIn("Current session 40% used", result["usage_text"])

    def test_create_window_uses_only_new_window_reference(self) -> None:
        with mock.patch("claude_starter.usage.run_osascript", return_value="42\n") as script:
            self.assertEqual(create_usage_terminal_window("/opt/homebrew/bin/claude"), 42)
        text = "\n".join(script.call_args.args[0])
        self.assertIn("set usageTab to (do script", text)
        self.assertNotIn("front window", text)
        self.assertNotIn("selected tab of front", text)

    def test_launch_command_uses_absolute_cli_and_unsets_api_credentials(self) -> None:
        command = usage_launch_command("/opt/homebrew/bin/claude")
        self.assertIn("-- /opt/homebrew/bin/claude --no-chrome", command)
        self.assertIn("-u ANTHROPIC_API_KEY", command)

    def test_session_sends_usage_and_closes_its_window(self) -> None:
        snapshots = iter(["Welcome to Claude Code", "Welcome to Claude Code\n/usage\n5h remaining 40%", "Welcome to Claude Code\n/usage\n5h remaining 40%"])
        with mock.patch("claude_starter.usage.create_usage_terminal_window", return_value=77), mock.patch("claude_starter.usage.terminal_window_contents", side_effect=lambda _: next(snapshots)), mock.patch("claude_starter.usage.send_usage_command") as send, mock.patch("claude_starter.usage.close_usage_terminal_window") as close, mock.patch("claude_starter.usage.time.sleep"):
            output = run_usage_session("/bin/claude", timeout_seconds=5, poll_interval_seconds=0)
        send.assert_called_once_with(77)
        close.assert_called_once_with(77)
        self.assertIn("5h remaining", output)

    def test_session_closes_window_when_startup_times_out(self) -> None:
        with mock.patch("claude_starter.usage.create_usage_terminal_window", return_value=77), mock.patch("claude_starter.usage.terminal_window_contents", return_value="starting"), mock.patch("claude_starter.usage.close_usage_terminal_window") as close, mock.patch("claude_starter.usage.time.monotonic", side_effect=[0, 11]):
            with self.assertRaises(AppError) as context:
                run_usage_session("/bin/claude", timeout_seconds=10, poll_interval_seconds=0)
        self.assertEqual(context.exception.code, ErrorCode.TIMEOUT)
        close.assert_called_once_with(77)

    def test_query_usage_rejects_busy_claude_run(self) -> None:
        capabilities = mock.Mock(executable="/usr/local/bin/claude", prohibited_credentials=[], auth_status="authenticated")
        with mock.patch("claude_starter.usage.discover_claude", return_value=capabilities), mock.patch("claude_starter.usage.FileLock.acquire", side_effect=AppError(ErrorCode.ALREADY_RUNNING)):
            with self.assertRaises(AppError) as context:
                query_usage(self.paths, self.config)
        self.assertEqual(context.exception.code, ErrorCode.ALREADY_RUNNING)

    def test_terminal_automation_error_is_clear(self) -> None:
        with mock.patch("claude_starter.usage.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=1, stdout="", stderr="Not authorized")
            from claude_starter.usage import run_osascript
            with self.assertRaises(AppError) as context:
                run_osascript(['tell application "Terminal" to return ""'])
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_USAGE_UNAVAILABLE)
        self.assertIn("Automation", context.exception.message)


if __name__ == "__main__":
    unittest.main()
