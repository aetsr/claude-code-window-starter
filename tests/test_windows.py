"""Tests for window scheduling engine."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from claude_starter.windows import (
    WINDOW_FIVE_HOUR,
    WINDOW_WEEKLY,
    advance_window,
    current_window_start,
    format_countdown,
    next_window_after,
    windows_due,
)


class WindowsTests(unittest.TestCase):
    """Test window calculation logic."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Reference anchor: 2025-01-15 10:00 UTC
        self.anchor = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        self.five_hour_interval = timedelta(hours=5, minutes=3)  # 303 minutes
        self.weekly_interval = timedelta(days=7)

    def test_next_window_after_before_anchor(self) -> None:
        """Before anchor is reached, next window should be the anchor."""
        now = self.anchor - timedelta(hours=1)
        next_win = next_window_after(self.anchor, self.five_hour_interval, now)
        self.assertEqual(next_win, self.anchor)

    def test_next_window_after_exact_anchor(self) -> None:
        """At exact anchor time, next window should be anchor + interval."""
        now = self.anchor
        next_win = next_window_after(self.anchor, self.five_hour_interval, now)
        expected = self.anchor + self.five_hour_interval
        self.assertEqual(next_win, expected)

    def test_next_window_after_one_interval_elapsed(self) -> None:
        """After one full interval, next window should be anchor + 2*interval."""
        now = self.anchor + self.five_hour_interval + timedelta(minutes=1)
        next_win = next_window_after(self.anchor, self.five_hour_interval, now)
        expected = self.anchor + (2 * self.five_hour_interval)
        self.assertEqual(next_win, expected)

    def test_next_window_after_partial_interval(self) -> None:
        """Partway through an interval, next window rounds up to next interval."""
        now = self.anchor + self.five_hour_interval + timedelta(minutes=30)
        next_win = next_window_after(self.anchor, self.five_hour_interval, now)
        expected = self.anchor + (2 * self.five_hour_interval)
        self.assertEqual(next_win, expected)

    def test_current_window_start_before_anchor(self) -> None:
        """Before anchor, current window start is the anchor."""
        now = self.anchor - timedelta(hours=1)
        win = current_window_start(self.anchor, self.five_hour_interval, now)
        self.assertEqual(win, self.anchor)

    def test_current_window_start_at_anchor(self) -> None:
        """At anchor, current window is the anchor."""
        now = self.anchor
        win = current_window_start(self.anchor, self.five_hour_interval, now)
        self.assertEqual(win, self.anchor)

    def test_current_window_start_mid_interval(self) -> None:
        """Midway through interval, current window is the interval start."""
        now = self.anchor + self.five_hour_interval + timedelta(minutes=30)
        win = current_window_start(self.anchor, self.five_hour_interval, now)
        expected = self.anchor + self.five_hour_interval
        self.assertEqual(win, expected)

    def test_windows_due_before_anchor(self) -> None:
        """No windows due before anchor time."""
        config = {
            "windows": {
                WINDOW_FIVE_HOUR: {
                    "enabled": True,
                    "anchor_iso": self.anchor.isoformat(),
                    "interval_minutes": 303,
                },
                WINDOW_WEEKLY: {
                    "enabled": False,
                    "anchor_iso": None,
                    "interval_minutes": 10080,
                },
            }
        }
        state: dict = {}
        now = self.anchor - timedelta(hours=1)
        due = windows_due(config, state, now)
        self.assertEqual(due, [])

    def test_windows_due_at_anchor(self) -> None:
        """At anchor time, window becomes due."""
        config = {
            "windows": {
                WINDOW_FIVE_HOUR: {
                    "enabled": True,
                    "anchor_iso": self.anchor.isoformat(),
                    "interval_minutes": 303,
                },
                WINDOW_WEEKLY: {
                    "enabled": False,
                    "anchor_iso": None,
                    "interval_minutes": 10080,
                },
            }
        }
        state: dict = {}
        now = self.anchor
        due = windows_due(config, state, now)
        self.assertIn(WINDOW_FIVE_HOUR, due)

    def test_windows_due_respects_next_run_at(self) -> None:
        """If next_run_at is in future, window is not due."""
        future_run = (self.anchor + self.five_hour_interval + timedelta(hours=1)).isoformat()
        config = {
            "windows": {
                WINDOW_FIVE_HOUR: {
                    "enabled": True,
                    "anchor_iso": self.anchor.isoformat(),
                    "interval_minutes": 303,
                },
            }
        }
        state = {
            f"{WINDOW_FIVE_HOUR}_next_run_at": future_run,
        }
        now = self.anchor + self.five_hour_interval + timedelta(minutes=30)
        due = windows_due(config, state, now)
        self.assertNotIn(WINDOW_FIVE_HOUR, due)

    def test_windows_due_both_windows(self) -> None:
        """Both windows can be due simultaneously."""
        config = {
            "windows": {
                WINDOW_FIVE_HOUR: {
                    "enabled": True,
                    "anchor_iso": self.anchor.isoformat(),
                    "interval_minutes": 303,
                },
                WINDOW_WEEKLY: {
                    "enabled": True,
                    "anchor_iso": self.anchor.isoformat(),
                    "interval_minutes": 10080,
                },
            }
        }
        state: dict = {}
        now = self.anchor
        due = windows_due(config, state, now)
        self.assertEqual(sorted(due), [WINDOW_FIVE_HOUR, WINDOW_WEEKLY])

    def test_windows_due_disabled_window_not_due(self) -> None:
        """Disabled windows are never due."""
        config = {
            "windows": {
                WINDOW_FIVE_HOUR: {
                    "enabled": False,
                    "anchor_iso": self.anchor.isoformat(),
                    "interval_minutes": 303,
                },
            }
        }
        state: dict = {}
        now = self.anchor
        due = windows_due(config, state, now)
        self.assertNotIn(WINDOW_FIVE_HOUR, due)

    def test_windows_due_no_anchor_not_due(self) -> None:
        """Windows without anchor configured are never due."""
        config = {
            "windows": {
                WINDOW_FIVE_HOUR: {
                    "enabled": True,
                    "anchor_iso": None,
                    "interval_minutes": 303,
                },
            }
        }
        state: dict = {}
        now = self.anchor
        due = windows_due(config, state, now)
        self.assertEqual(due, [])

    def test_advance_window_five_hour(self) -> None:
        """After triggering, advance_window computes next run."""
        config = {
            "windows": {
                WINDOW_FIVE_HOUR: {
                    "enabled": True,
                    "anchor_iso": self.anchor.isoformat(),
                    "interval_minutes": 303,
                },
            }
        }
        now = self.anchor
        next_run = advance_window(WINDOW_FIVE_HOUR, config, now)
        expected = self.anchor + self.five_hour_interval
        self.assertEqual(next_run, expected)

    def test_advance_window_weekly(self) -> None:
        """Weekly windows advance by 7 days."""
        config = {
            "windows": {
                WINDOW_WEEKLY: {
                    "enabled": True,
                    "anchor_iso": self.anchor.isoformat(),
                    "interval_minutes": 10080,
                },
            }
        }
        now = self.anchor
        next_run = advance_window(WINDOW_WEEKLY, config, now)
        expected = self.anchor + self.weekly_interval
        self.assertEqual(next_run, expected)

    def test_advance_window_missing_config_raises(self) -> None:
        """Advance window raises if window not configured."""
        config = {"windows": {}}
        with self.assertRaises(ValueError):
            advance_window(WINDOW_FIVE_HOUR, config)

    def test_format_countdown_days(self) -> None:
        """Countdown with days."""
        target = datetime(2025, 1, 20, 14, 30, 0, tzinfo=timezone.utc)
        now = datetime(2025, 1, 17, 10, 10, 0, tzinfo=timezone.utc)
        # Delta: 3 days + 4 hours + 20 minutes
        result = format_countdown(target, now)
        self.assertIn("3g", result)
        self.assertIn("4s", result)
        self.assertIn("20dk", result)

    def test_format_countdown_no_days(self) -> None:
        """Countdown with hours and minutes only."""
        target = datetime(2025, 1, 17, 14, 30, 0, tzinfo=timezone.utc)
        now = datetime(2025, 1, 17, 10, 10, 0, tzinfo=timezone.utc)
        # Delta: 4 hours 20 minutes
        result = format_countdown(target, now)
        self.assertIn("4s", result)
        self.assertIn("20dk", result)
        self.assertNotIn("g", result)

    def test_format_countdown_minutes_only(self) -> None:
        """Countdown with minutes only."""
        target = datetime(2025, 1, 17, 10, 45, 0, tzinfo=timezone.utc)
        now = datetime(2025, 1, 17, 10, 10, 0, tzinfo=timezone.utc)
        # Delta: 35 minutes
        result = format_countdown(target, now)
        self.assertEqual("35dk", result)

    def test_format_countdown_now(self) -> None:
        """Countdown at exact time or in past returns 'Şimdi'."""
        target = datetime(2025, 1, 17, 10, 10, 0, tzinfo=timezone.utc)
        now = datetime(2025, 1, 17, 10, 10, 0, tzinfo=timezone.utc)
        result = format_countdown(target, now)
        self.assertEqual("Şimdi", result)

    def test_format_countdown_past(self) -> None:
        """Countdown in past returns 'Şimdi'."""
        target = datetime(2025, 1, 17, 10, 0, 0, tzinfo=timezone.utc)
        now = datetime(2025, 1, 17, 10, 10, 0, tzinfo=timezone.utc)
        result = format_countdown(target, now)
        self.assertEqual("Şimdi", result)

    def test_format_countdown_zero_hours_shown(self) -> None:
        """If hours or days are zero, they're not shown."""
        target = datetime(2025, 1, 17, 10, 35, 0, tzinfo=timezone.utc)
        now = datetime(2025, 1, 17, 10, 0, 0, tzinfo=timezone.utc)
        # Delta: 35 minutes (0 days, 0 hours)
        result = format_countdown(target, now)
        self.assertEqual("35dk", result)
        self.assertNotIn("g", result)
        self.assertNotIn("s", result)

    def test_dst_safe_utc_anchor(self) -> None:
        """UTC anchor is not affected by DST transitions."""
        # March 2025: DST starts in many regions
        # Create anchor in UTC — should be unaffected
        anchor_before_dst = datetime(2025, 3, 8, 10, 0, 0, tzinfo=timezone.utc)
        interval = timedelta(hours=5, minutes=3)

        # Compute window after DST transition (in local time)
        now_after_dst = datetime(2025, 3, 10, 10, 0, 0, tzinfo=timezone.utc)

        next_win = next_window_after(anchor_before_dst, interval, now_after_dst)

        # Should be 5h3m from now, not affected by DST
        # Calculate how many intervals have passed
        elapsed = now_after_dst - anchor_before_dst
        n = int(elapsed / interval)
        expected = anchor_before_dst + (n + 1) * interval

        self.assertEqual(next_win, expected)

    def test_negative_interval_hours(self) -> None:
        """Partial hour intervals work correctly."""
        # 5 hours 30 minutes
        interval = timedelta(hours=5, minutes=30)
        now = self.anchor + interval + timedelta(minutes=15)
        next_win = next_window_after(self.anchor, interval, now)
        expected = self.anchor + (2 * interval)
        self.assertEqual(next_win, expected)


if __name__ == "__main__":
    unittest.main()
