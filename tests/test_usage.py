from __future__ import annotations

import unittest
from unittest import mock

from claude_starter.errors import AppError, ErrorCode
from claude_starter.usage import (
    SessionSnapshot,
    format_usage_message,
    query_active_session_usage,
    strip_ansi,
    suffix_delta,
)


class UsageTests(unittest.TestCase):
    def test_strip_ansi_removes_escape_sequences(self) -> None:
        value = "\x1b[31mUsage: 52%\x1b[0m"
        self.assertEqual(strip_ansi(value), "Usage: 52%")

    def test_suffix_delta_prefers_overlap(self) -> None:
        before = ["line1", "line2", "line3"]
        after = ["line2", "line3", "/usage", "5h remaining 40%"]
        self.assertEqual(suffix_delta(before, after), ["/usage", "5h remaining 40%"])

    def test_format_usage_message_builds_bullets(self) -> None:
        text = "/usage\n5h remaining 40%\nWeekly remaining 82%\nReset in 2h"
        message = format_usage_message(text)
        self.assertIn("Claude Kullanım Bilgisi", message)
        self.assertIn("• 5h remaining 40%", message)
        self.assertNotIn("/usage", message)

    def test_query_active_session_usage_reports_missing_session(self) -> None:
        snapshot = SessionSnapshot("Terminal", "ttys001", "Claude", "ready")
        with (
            mock.patch("claude_starter.usage.active_session_snapshot", return_value=snapshot),
            mock.patch("claude_starter.usage.tty_has_claude", return_value=False),
        ):
            with self.assertRaises(AppError) as context:
                query_active_session_usage(timeout_seconds=0, poll_interval_seconds=0)
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_SESSION_UNAVAILABLE)

    def test_query_active_session_usage_returns_formatted_result(self) -> None:
        before = SessionSnapshot("Terminal", "ttys001", "Claude", "prompt")
        after = SessionSnapshot(
            "Terminal",
            "ttys001",
            "Claude",
            "prompt\n/usage\n5h remaining 40%\nWeekly remaining 82%\nReset in 2h",
        )
        with (
            mock.patch(
                "claude_starter.usage.active_session_snapshot",
                side_effect=[before, after, after],
            ),
            mock.patch("claude_starter.usage.tty_has_claude", return_value=True),
            mock.patch("claude_starter.usage.send_usage_command"),
            mock.patch("claude_starter.usage.time.sleep"),
        ):
            result = query_active_session_usage(timeout_seconds=1, poll_interval_seconds=0)
        self.assertIn("5h remaining 40%", result["usage_text"])
        self.assertIn("Claude Kullanım Bilgisi", result["formatted_text"])


if __name__ == "__main__":
    unittest.main()
