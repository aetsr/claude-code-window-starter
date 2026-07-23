from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from claude_starter.logging_utils import log_event, sanitize, sanitize_text, tail_sanitized
from claude_starter.paths import AppPaths


class LoggingTests(unittest.TestCase):
    def test_known_secret_patterns_are_redacted(self) -> None:
        value = sanitize_text(
            "token="
            + "123456789:"
            + "abcdefghijklmnopqrstuvwxyzABCDE "
            + "sk-ant-"
            + "abcdefghijklmnop"
        )
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", value)
        self.assertNotIn("sk-ant-", value)

    def test_sensitive_key_values_are_redacted(self) -> None:
        result = sanitize({"telegram_token": "secret", "status": "ok"})
        self.assertEqual(result["telegram_token"], "[REDACTED]")
        self.assertEqual(result["status"], "ok")

    def test_log_file_is_private_and_tail_is_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            log_event(paths, {"authorization": "Bearer abcdefghijklmnop", "status": "ok"})
            self.assertEqual(paths.log_file.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("abcdefghijklmnop", "\n".join(tail_sanitized(paths.log_file)))


if __name__ == "__main__":
    unittest.main()
