from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from claude_starter.paths import AppPaths
from claude_starter.usage import (
    FIVE_HOURS,
    captured_rate_limits,
    next_window_time,
    normalized_rate_limits,
)


class UsageWindowTests(unittest.TestCase):
    def test_official_five_hour_window_is_normalized(self) -> None:
        value = normalized_rate_limits(
            {
                "five_hour": {"used_percentage": 12.345, "resets_at": 2_000_000_000},
                "seven_day": {"used_percentage": 44, "resets_at": 2_000_100_000},
            }
        )
        self.assertIsNotNone(value)
        self.assertEqual(value["five_hour"]["used_percentage"], 12.35)  # type: ignore[index]

    def test_invalid_or_missing_window_is_rejected(self) -> None:
        self.assertIsNone(normalized_rate_limits({}))
        self.assertIsNone(
            normalized_rate_limits(
                {"five_hour": {"used_percentage": 101, "resets_at": 2_000_000_000}}
            )
        )

    def test_official_reset_wins_over_estimate(self) -> None:
        completed = datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
        reset = completed + timedelta(hours=4)
        next_at, verified = next_window_time(
            {
                "five_hour": {
                    "used_percentage": 1,
                    "resets_at": int(reset.timestamp()),
                }
            },
            completed_at=completed,
            grace_seconds=60,
        )
        self.assertTrue(verified)
        self.assertEqual(next_at, reset + timedelta(seconds=60))

    def test_missing_official_reset_uses_five_hour_estimate(self) -> None:
        completed = datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
        next_at, verified = next_window_time(None, completed_at=completed, grace_seconds=60)
        self.assertFalse(verified)
        self.assertEqual(next_at, completed + FIVE_HOURS)

    def test_corrupted_usage_capture_file_is_ignored(self) -> None:
        with TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            paths.usage_status_file.write_text("{not-json", encoding="utf-8")
            self.assertIsNone(captured_rate_limits(paths, newer_than=0))
