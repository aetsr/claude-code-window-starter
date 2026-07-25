from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from claude_starter.config import DEFAULT_CONFIG, load_config, save_config
from claude_starter.errors import AppError, ErrorCode
from claude_starter.io_utils import atomic_write_json
from claude_starter.locks import FileLock
from claude_starter.paths import AppPaths
from claude_starter.scheduler import windows_due, next_runs
from claude_starter.state import load_state, update_state
from claude_starter.windows import advance_window, get_interval, current_window_start


class ConfigStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temporary.name))
        self.paths.ensure()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_config_is_safe_and_created_atomically(self) -> None:
        config = load_config(self.paths, create=True)
        self.assertEqual(config["schema_version"], 3)
        self.assertFalse(config["enabled"])
        self.assertFalse(config["background_enabled"])
        self.assertFalse(config["telegram"]["enabled"])
        self.assertIn("windows", config)
        self.assertIn("five_hour", config["windows"])
        self.assertIn("weekly", config["windows"])
        self.assertEqual(self.paths.config_file.stat().st_mode & 0o777, 0o600)

    def test_v1_config_migrates_to_v3(self) -> None:
        old = json.loads(json.dumps(DEFAULT_CONFIG))
        old["schema_version"] = 1
        old["automation_mode"] = "daily"
        old["schedule_time"] = "09:00"
        old["removed_target"] = "legacy"
        atomic_write_json(self.paths.config_file, old)
        value = load_config(self.paths)
        self.assertEqual(value["schema_version"], 3)
        self.assertNotIn("automation_mode", value)
        self.assertNotIn("schedule_time", value)
        self.assertNotIn("removed_target", value)

    def test_v2_config_migrates_to_v3(self) -> None:
        old = json.loads(json.dumps(DEFAULT_CONFIG))
        old["schema_version"] = 2
        atomic_write_json(self.paths.config_file, old)
        value = load_config(self.paths)
        self.assertEqual(value["schema_version"], 3)

    def test_string_schema_versions_are_accepted(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["schema_version"] = "3"
        atomic_write_json(self.paths.config_file, config)
        self.assertEqual(load_config(self.paths)["schema_version"], 3)

        atomic_write_json(self.paths.state_file, {"schema_version": "3"})
        self.assertEqual(load_state(self.paths)["schema_version"], 3)

    def test_invalid_window_anchor_rejected(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["windows"]["five_hour"]["anchor_iso"] = "not-a-valid-iso"
        with self.assertRaises(AppError) as context:
            save_config(self.paths, config)
        self.assertEqual(context.exception.code, ErrorCode.CONFIG_INVALID)

    def test_invalid_interval_minutes_rejected(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["windows"]["five_hour"]["interval_minutes"] = -10
        with self.assertRaises(AppError) as context:
            save_config(self.paths, config)
        self.assertEqual(context.exception.code, ErrorCode.CONFIG_INVALID)

    def test_state_migration_v1_to_v3(self) -> None:
        old_state = {
            "schema_version": 1,
            "usage_window": "verified",
            "next_window_run_at": "2026-07-25T12:00:00+00:00",
            "automatic_blocked": {"error_code": "SOME_ERROR"},
            "pending_automatic": True,
        }
        atomic_write_json(self.paths.state_file, old_state)
        state = load_state(self.paths)
        self.assertEqual(state["schema_version"], 3)
        self.assertNotIn("usage_window", state)
        self.assertNotIn("next_window_run_at", state)
        self.assertNotIn("automatic_blocked", state)
        self.assertNotIn("pending_automatic", state)
        # New fields should exist
        self.assertIn("five_hour_next_run_at", state)
        self.assertIn("weekly_next_run_at", state)

    def test_state_update_preserves_schema(self) -> None:
        now = datetime.now(timezone.utc)
        state = update_state(
            self.paths,
            lambda current: current.__setitem__("five_hour_next_run_at", now.isoformat())
        )
        self.assertEqual(state["five_hour_next_run_at"], now.isoformat())
        self.assertEqual(load_state(self.paths)["schema_version"], 3)

    def test_second_lock_is_rejected(self) -> None:
        with FileLock(self.paths.run_lock):
            with self.assertRaises(AppError) as context:
                with FileLock(self.paths.run_lock):
                    pass
        self.assertEqual(context.exception.code, ErrorCode.LOCK_UNAVAILABLE)

    def test_windows_due_respects_config_enabled(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["windows"]["five_hour"]["enabled"] = False
        config["windows"]["five_hour"]["anchor_iso"] = "2026-07-25T11:00:00+00:00"
        now = datetime.now(timezone.utc)
        due = windows_due(self.paths, config)
        self.assertNotIn("five_hour", due)

    def test_windows_due_requires_anchor_iso(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["windows"]["five_hour"]["enabled"] = True
        config["windows"]["five_hour"]["anchor_iso"] = None
        now = datetime.now(timezone.utc)
        due = windows_due(self.paths, config)
        self.assertNotIn("five_hour", due)

    def test_atomic_json_replaces_complete_document(self) -> None:
        atomic_write_json(self.paths.state_file, {"schema_version": 3, "value": "old"})
        atomic_write_json(self.paths.state_file, {"schema_version": 3, "value": "new"})
        self.assertEqual(json.loads(self.paths.state_file.read_text())["value"], "new")

    def test_v3_config_with_unknown_fields_loads_successfully(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["removed_legacy_field"] = "old_value"
        config["telegram"]["legacy_notify_updates"] = True
        atomic_write_json(self.paths.config_file, config)
        loaded = load_config(self.paths)
        self.assertNotIn("removed_legacy_field", loaded)
        self.assertNotIn("legacy_notify_updates", loaded.get("telegram", {}))
        self.assertEqual(loaded["schema_version"], 3)

    def test_save_config_still_rejects_unknown_fields(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["telegram"]["unknown_new_field"] = True
        with self.assertRaises(AppError) as context:
            save_config(self.paths, config)
        self.assertEqual(context.exception.code, ErrorCode.CONFIG_INVALID)

    def test_advance_window_computation(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        anchor = datetime(2026, 7, 25, 11, 0, 0, tzinfo=timezone.utc)
        config["windows"]["five_hour"]["anchor_iso"] = anchor.isoformat()
        config["windows"]["five_hour"]["interval_minutes"] = 303

        now = datetime(2026, 7, 25, 11, 30, 0, tzinfo=timezone.utc)
        next_at = advance_window("five_hour", config, now)

        # 303 minutes from anchor = 5 hours 3 minutes
        expected_interval = 303 * 60  # seconds
        expected = datetime(2026, 7, 25, 16, 3, 0, tzinfo=timezone.utc)
        self.assertEqual(next_at, expected)

    def test_next_runs_computation(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        anchor = datetime(2026, 7, 25, 10, 0, 0, tzinfo=timezone.utc)
        config["windows"]["five_hour"]["enabled"] = True
        config["windows"]["five_hour"]["anchor_iso"] = anchor.isoformat()
        config["windows"]["five_hour"]["interval_minutes"] = 303

        runs = next_runs(self.paths, config)
        self.assertIn("five_hour", runs)
        self.assertGreater(runs["five_hour"], datetime.now(timezone.utc))

    def test_validate_config_accepts_z_suffix_anchor_when_enabled(self) -> None:
        """validate_config must accept Z-suffix anchor_iso (Swift format) when window enabled."""
        from claude_starter.config import validate_config
        import copy

        config = copy.deepcopy(DEFAULT_CONFIG)
        config["windows"]["five_hour"]["enabled"] = True
        config["windows"]["five_hour"]["anchor_iso"] = "2026-07-25T18:43:00Z"
        # Should not raise
        result = validate_config(config)
        self.assertEqual(result["windows"]["five_hour"]["anchor_iso"], "2026-07-25T18:43:00Z")

    def test_validate_config_accepts_z_suffix_anchor_when_disabled(self) -> None:
        """validate_config must accept Z-suffix anchor even when window is disabled."""
        from claude_starter.config import validate_config
        import copy

        config = copy.deepcopy(DEFAULT_CONFIG)
        config["windows"]["five_hour"]["enabled"] = False
        config["windows"]["five_hour"]["anchor_iso"] = "2026-07-25T18:43:00Z"
        # Should not raise regardless of enabled state
        result = validate_config(config)
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
