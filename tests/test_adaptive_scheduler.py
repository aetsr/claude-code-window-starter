from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from claude_starter.claude import ANCHOR_PROMPT, run_anchor
from claude_starter.config import DEFAULT_CONFIG, load_config
from claude_starter.errors import AppError, ErrorCode
from claude_starter.io_utils import atomic_write_json
from claude_starter.locks import FileLock
from claude_starter.paths import AppPaths
from claude_starter.scheduler import ideal_actions_for_day, schedule_snapshot, tick_schedule
from claude_starter.state import load_state
from claude_starter.usage import parse_usage_limits


def adaptive_config() -> dict:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config["enabled"] = True
    config["timezone"] = "Europe/Berlin"
    return config


class UsageLimitParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)

    def test_relative_and_absolute_resets(self) -> None:
        parsed = parse_usage_limits(
            """Current session
23% used
Resets in 4 hr 12 min
Current week (all models)
81% used
Resets Aug 28 at 5pm""",
            now=self.now,
            timezone_name="Europe/Berlin",
        )
        self.assertEqual(parsed["five_hour"]["used_percentage"], 23.0)  # type: ignore[index]
        self.assertEqual(parsed["five_hour"]["resets_at"], "2026-08-26T14:12:00+00:00")  # type: ignore[index]
        self.assertEqual(parsed["weekly"]["resets_at"], "2026-08-28T15:00:00+00:00")  # type: ignore[index]

    def test_am_pm_year_rollover_and_weekly_limit(self) -> None:
        parsed = parse_usage_limits(
            "5 hour 0% resets at 3:30 PM\nWeekly 100% resets Jan 2 at 8am",
            now=datetime(2026, 12, 31, 20, tzinfo=timezone.utc),
            timezone_name="Europe/Berlin",
        )
        self.assertEqual(parsed["weekly"]["used_percentage"], 100.0)  # type: ignore[index]
        self.assertTrue(str(parsed["weekly"]["resets_at"]).startswith("2027-01-02"))  # type: ignore[index]

    def test_malformed_output_returns_empty_limits(self) -> None:
        self.assertEqual(
            parse_usage_limits("not a usage response", now=self.now),
            {"five_hour": None, "weekly": None},
        )


class AdaptivePlanningTests(unittest.TestCase):
    def test_default_busy_day_has_expected_balanced_actions(self) -> None:
        config = adaptive_config()
        zone = ZoneInfo("Europe/Berlin")
        actions = ideal_actions_for_day(config, date(2026, 8, 24))
        local = [
            datetime.fromisoformat(action["scheduled_at"]).astimezone(zone).strftime("%H:%M")
            for action in actions
        ]
        self.assertEqual(local, ["05:00", "10:03", "15:06"])

    def test_weekend_is_skipped_and_next_action_is_monday(self) -> None:
        config = adaptive_config()
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            now = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
            snapshot = schedule_snapshot(paths, config, now=now)
            self.assertEqual(snapshot["today_actions"], [])
            next_local = datetime.fromisoformat(snapshot["next_action_at"]).astimezone(
                ZoneInfo("Europe/Berlin")
            )
            self.assertEqual((next_local.isoweekday(), next_local.strftime("%H:%M")), (1, "05:00"))

    def test_dst_keeps_local_action_times(self) -> None:
        config = adaptive_config()
        zone = ZoneInfo("Europe/Berlin")
        before = ideal_actions_for_day(config, date(2026, 3, 27))[0]
        after = ideal_actions_for_day(config, date(2026, 3, 30))[0]
        self.assertEqual(datetime.fromisoformat(before["scheduled_at"]).astimezone(zone).hour, 5)
        self.assertEqual(datetime.fromisoformat(after["scheduled_at"]).astimezone(zone).hour, 5)

    def test_v3_migration_preserves_manual_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            old = json.loads(json.dumps(DEFAULT_CONFIG))
            old["schema_version"] = 3
            for key in (
                "mode",
                "busy_start_local",
                "busy_end_local",
                "active_weekdays",
                "strategy",
                "reset_grace_seconds",
            ):
                old["windows"]["five_hour"].pop(key)
            atomic_write_json(paths.config_file, old)
            self.assertEqual(load_config(paths)["windows"]["five_hour"]["mode"], "manual")


class SchedulerTickTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.directory.name))
        self.paths.ensure()
        self.config = adaptive_config()
        self.now = datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc)  # 05:00 Berlin

    def tearDown(self) -> None:
        self.directory.cleanup()

    def observation(self, *, reset_hours: int | None = None, weekly: float = 20) -> dict:
        reset = self.now + timedelta(hours=reset_hours) if reset_hours is not None else None
        return {
            "captured_at": self.now.isoformat(),
            "source": "claude_code_usage",
            "limits": {
                "five_hour": {
                    "used_percentage": 10.0,
                    "resets_at": reset.isoformat() if reset else None,
                },
                "weekly": {"used_percentage": weekly, "resets_at": None},
            },
        }

    @mock.patch("claude_starter.claude.run_anchor", return_value={"selected_model": "haiku"})
    @mock.patch("claude_starter.usage.query_usage")
    def test_observe_then_anchor_and_deduplicate(self, query: mock.Mock, anchor: mock.Mock) -> None:
        query.return_value = self.observation()
        first = tick_schedule(self.paths, self.config, now=self.now)
        second = tick_schedule(self.paths, self.config, now=self.now)
        self.assertEqual(first["event"], "anchor_succeeded")
        self.assertEqual(second["event"], "no_action")
        anchor.assert_called_once()

    @mock.patch("claude_starter.claude.run_anchor")
    @mock.patch("claude_starter.usage.query_usage")
    def test_manual_window_replans_without_ping(self, query: mock.Mock, anchor: mock.Mock) -> None:
        query.return_value = self.observation(reset_hours=4)
        result = tick_schedule(self.paths, self.config, now=self.now)
        self.assertEqual(result["event"], "manual_window_detected")
        anchor.assert_not_called()
        self.assertEqual(result["confidence"], "observed")

    @mock.patch("claude_starter.claude.run_anchor", return_value={"selected_model": "haiku"})
    @mock.patch("claude_starter.usage.query_usage")
    def test_measurement_failure_is_estimated_and_attempted_once(
        self, query: mock.Mock, anchor: mock.Mock
    ) -> None:
        query.side_effect = AppError(ErrorCode.NETWORK_UNAVAILABLE)
        result = tick_schedule(self.paths, self.config, now=self.now)
        self.assertEqual(result["event"], "anchor_succeeded")
        completed = load_state(self.paths)["schedule_action_results"]
        self.assertEqual(next(iter(completed.values()))["confidence"], "estimated")
        tick_schedule(self.paths, self.config, now=self.now)
        anchor.assert_called_once()

    @mock.patch("claude_starter.claude.run_anchor")
    @mock.patch("claude_starter.usage.query_usage")
    def test_weekly_exhaustion_stops_anchor(self, query: mock.Mock, anchor: mock.Mock) -> None:
        query.return_value = self.observation(weekly=100)
        result = tick_schedule(self.paths, self.config, now=self.now)
        self.assertEqual(result["event"], "weekly_exhausted")
        anchor.assert_not_called()

    def test_schedule_lock_collision_is_rejected(self) -> None:
        with FileLock(self.paths.runtime_dir / "schedule.lock"):
            with self.assertRaises(AppError) as context:
                tick_schedule(self.paths, self.config, now=self.now)
        self.assertEqual(context.exception.code, ErrorCode.ALREADY_RUNNING)

    @mock.patch("claude_starter.claude.run_anchor")
    @mock.patch("claude_starter.usage.query_usage")
    def test_stale_offline_actions_are_not_replayed(
        self, query: mock.Mock, anchor: mock.Mock
    ) -> None:
        late = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)  # 12:00 Berlin
        result = tick_schedule(self.paths, self.config, now=late)
        self.assertEqual(result["event"], "missed_not_replayed")
        query.assert_not_called()
        anchor.assert_not_called()


class AnchorSafetyTests(unittest.TestCase):
    @mock.patch("claude_starter.claude.run_claude", return_value={"selected_model": "haiku"})
    def test_anchor_forces_fixed_haiku_prompt_without_fallback(self, run: mock.Mock) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            config = adaptive_config()
            config["model"] = "opus"
            config["prompt"] = "user task must not run"
            run_anchor(paths, config)
        anchor_config = run.call_args.args[1]
        self.assertEqual(anchor_config["model"], "haiku")
        self.assertEqual(anchor_config["prompt"], ANCHOR_PROMPT)
        self.assertEqual(run.call_args.kwargs["trigger"], "adaptive_anchor")
