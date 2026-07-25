from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from claude_starter.config import DEFAULT_CONFIG, load_config, save_config
from claude_starter.errors import AppError, ErrorCode
from claude_starter.io_utils import atomic_write_json
from claude_starter.locks import FileLock
from claude_starter.paths import AppPaths
from claude_starter.scheduler import automatic_due, clear_pending, mark_pending, next_run
from claude_starter.state import load_state, update_state


class ConfigStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temporary.name))
        self.paths.ensure()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_config_is_safe_and_created_atomically(self) -> None:
        config = load_config(self.paths, create=True)
        self.assertEqual(config["schema_version"], 2)
        self.assertFalse(config["enabled"])
        self.assertFalse(config["background_enabled"])
        self.assertFalse(config["telegram"]["enabled"])
        self.assertEqual(self.paths.config_file.stat().st_mode & 0o777, 0o600)

    def test_v1_config_migrates_without_removed_fields(self) -> None:
        old = json.loads(json.dumps(DEFAULT_CONFIG))
        old["schema_version"] = 1
        old["removed_target"] = "legacy"
        old["removed_release"] = {"enabled": True}
        atomic_write_json(self.paths.config_file, old)
        value = load_config(self.paths)
        self.assertEqual(value["schema_version"], 2)
        self.assertNotIn("removed_target", value)
        self.assertNotIn("removed_release", value)

    def test_string_schema_versions_are_accepted(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["schema_version"] = "2"
        atomic_write_json(self.paths.config_file, config)
        self.assertEqual(load_config(self.paths)["schema_version"], 2)

        atomic_write_json(self.paths.state_file, {"schema_version": "2"})
        self.assertEqual(load_state(self.paths)["schema_version"], 2)

    def test_invalid_schedule_and_unknown_field_rejected(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["schedule_time"] = "25:00"
        with self.assertRaises(AppError) as context:
            save_config(self.paths, config)
        self.assertEqual(context.exception.code, ErrorCode.CONFIG_INVALID)
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["telegram"]["unknown"] = True
        with self.assertRaises(AppError):
            save_config(self.paths, config)

    def test_state_update_preserves_schema(self) -> None:
        state = update_state(
            self.paths, lambda current: current.__setitem__("last_automatic_date", "2026-07-23")
        )
        self.assertEqual(state["last_automatic_date"], "2026-07-23")
        self.assertEqual(load_state(self.paths)["schema_version"], 2)

    def test_second_lock_is_rejected(self) -> None:
        with FileLock(self.paths.run_lock):
            with self.assertRaises(AppError) as context:
                with FileLock(self.paths.run_lock):
                    pass
        self.assertEqual(context.exception.code, ErrorCode.LOCK_UNAVAILABLE)

    def test_next_run_and_pending_due(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["enabled"] = True
        config["automation_mode"] = "daily"
        now = datetime(2026, 7, 23, 9, 0, tzinfo=ZoneInfo("Europe/Istanbul"))
        self.assertEqual(next_run(config, now).date().isoformat(), "2026-07-24")
        self.assertTrue(automatic_due(self.paths, config, now))
        update_state(
            self.paths, lambda state: state.__setitem__("last_automatic_date", "2026-07-23")
        )
        self.assertFalse(automatic_due(self.paths, config, now))

    def test_pending_connectivity_uses_backoff_then_retries(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["enabled"] = True
        mark_pending(self.paths, config, "NETWORK_UNAVAILABLE")
        self.assertFalse(automatic_due(self.paths, config))
        update_state(
            self.paths,
            lambda state: state.__setitem__("next_automatic_retry_at", "2000-01-01T00:00:00+00:00"),
        )
        self.assertTrue(automatic_due(self.paths, config))
        clear_pending(self.paths)
        self.assertIsNone(load_state(self.paths)["pending_automatic"])

    def test_permanent_automatic_failure_blocks_request_storm(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["enabled"] = True
        update_state(
            self.paths,
            lambda state: state.__setitem__(
                "automatic_blocked",
                {"error_code": "CLAUDE_NOT_AUTHENTICATED"},
            ),
        )
        self.assertFalse(automatic_due(self.paths, config))

    def test_atomic_json_replaces_complete_document(self) -> None:
        atomic_write_json(self.paths.state_file, {"schema_version": 2, "value": "old"})
        atomic_write_json(self.paths.state_file, {"schema_version": 2, "value": "new"})
        self.assertEqual(json.loads(self.paths.state_file.read_text())["value"], "new")

    def test_v2_config_with_unknown_fields_loads_successfully(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["removed_legacy_field"] = "old_value"
        config["telegram"]["legacy_notify_updates"] = True
        atomic_write_json(self.paths.config_file, config)
        loaded = load_config(self.paths)
        self.assertNotIn("removed_legacy_field", loaded)
        self.assertNotIn("legacy_notify_updates", loaded.get("telegram", {}))
        self.assertEqual(loaded["schema_version"], 2)

    def test_save_config_still_rejects_unknown_fields(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["telegram"]["unknown_new_field"] = True
        with self.assertRaises(AppError) as context:
            save_config(self.paths, config)
        self.assertEqual(context.exception.code, ErrorCode.CONFIG_INVALID)
