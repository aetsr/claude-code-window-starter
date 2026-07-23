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
from claude_starter.scheduler import catch_up_due, next_run
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
        self.assertFalse(config["enabled"])
        self.assertFalse(config["telegram"]["enabled"])
        self.assertFalse(config["deployment"]["auto_apply_updates"])
        self.assertEqual(self.paths.config_file.stat().st_mode & 0o777, 0o600)

    def test_invalid_schedule_is_rejected(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["schedule_time"] = "25:00"
        with self.assertRaises(AppError) as context:
            save_config(self.paths, config)
        self.assertEqual(context.exception.code, ErrorCode.CONFIG_INVALID)

    def test_unknown_nested_config_field_is_rejected(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["deployment"]["private_key"] = "must-never-be-configured-here"
        with self.assertRaises(AppError) as context:
            save_config(self.paths, config)
        self.assertEqual(context.exception.code, ErrorCode.CONFIG_INVALID)

    def test_telegram_requires_numeric_allowlist(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["telegram"]["enabled"] = True
        config["telegram"]["allowed_user_ids"] = ["123"]
        with self.assertRaises(AppError):
            save_config(self.paths, config)

    def test_state_update_preserves_schema(self) -> None:
        state = update_state(
            self.paths, lambda current: current.__setitem__("last_automatic_date", "2026-07-23")
        )
        self.assertEqual(state["last_automatic_date"], "2026-07-23")
        self.assertEqual(load_state(self.paths)["schema_version"], 1)

    def test_second_lock_is_rejected(self) -> None:
        with FileLock(self.paths.run_lock):
            with self.assertRaises(AppError) as context:
                with FileLock(self.paths.run_lock):
                    pass
        self.assertEqual(context.exception.code, ErrorCode.LOCK_UNAVAILABLE)

    def test_next_run_and_same_day_catchup(self) -> None:
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["enabled"] = True
        now = datetime(2026, 7, 23, 9, 0, tzinfo=ZoneInfo("Europe/Istanbul"))
        self.assertEqual(next_run(config, now).date().isoformat(), "2026-07-24")
        self.assertTrue(catch_up_due(self.paths, config, now))
        update_state(
            self.paths, lambda state: state.__setitem__("last_automatic_date", "2026-07-23")
        )
        self.assertFalse(catch_up_due(self.paths, config, now))

    def test_atomic_json_replaces_complete_document(self) -> None:
        atomic_write_json(self.paths.state_file, {"schema_version": 1, "value": "old"})
        atomic_write_json(self.paths.state_file, {"schema_version": 1, "value": "new"})
        self.assertEqual(json.loads(self.paths.state_file.read_text())["value"], "new")


if __name__ == "__main__":
    unittest.main()
