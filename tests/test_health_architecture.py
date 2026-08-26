from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter.errors import AppError, ErrorCode
from claude_starter.health import _telegram_supervisor_status, diagnose, health_report
from claude_starter.paths import AppPaths


class ArchitectureTests(unittest.TestCase):
    def test_arm64_and_x86_64_paths_are_supported(self) -> None:
        for architecture in ("aarch64", "arm64", "x86_64"):
            with (
                self.subTest(architecture=architecture),
                tempfile.TemporaryDirectory() as directory,
            ):
                with (
                    mock.patch("platform.system", return_value="Darwin"),
                    mock.patch("platform.machine", return_value=architecture),
                ):
                    report = diagnose(AppPaths(Path(directory)))
                self.assertEqual(report["environment"]["machine"], architecture)

    def test_unknown_architecture_stops_safely(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch("platform.system", return_value="Darwin"),
            mock.patch("platform.machine", return_value="mips"),
        ):
            with self.assertRaises(AppError) as context:
                diagnose(AppPaths(Path(directory)))
        self.assertEqual(context.exception.code, ErrorCode.UNSUPPORTED_ARCH)

    def test_non_mac_os_stops_safely(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch("platform.system", return_value="Linux"),
        ):
            with self.assertRaises(AppError) as context:
                diagnose(AppPaths(Path(directory)))
        self.assertEqual(context.exception.code, ErrorCode.UNSUPPORTED_OS)


class TelegramSupervisorStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temporary.name))
        self.paths.ensure()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_missing_status_file_returns_empty_dict(self) -> None:
        self.assertEqual(_telegram_supervisor_status(self.paths), {})

    def test_alive_supervisor_is_detected(self) -> None:
        status = {
            "supervisor_pid": os.getpid(),
            "token_available": True,
            "worker_running": True,
            "checked_at": "2026-01-01T00:00:00Z",
        }
        status_file = self.paths.runtime_dir / "telegram_supervisor.json"
        status_file.write_text(json.dumps(status))
        result = _telegram_supervisor_status(self.paths)
        self.assertTrue(result["supervisor_alive"])
        self.assertTrue(result["token_available"])
        self.assertTrue(result["worker_running"])

    def test_dead_supervisor_is_detected(self) -> None:
        status = {
            "supervisor_pid": 2147483647,
            "token_available": True,
            "worker_running": True,
        }
        status_file = self.paths.runtime_dir / "telegram_supervisor.json"
        status_file.write_text(json.dumps(status))
        result = _telegram_supervisor_status(self.paths)
        self.assertFalse(result["supervisor_alive"])

    def test_health_report_includes_telegram_check(self) -> None:
        from claude_starter.config import DEFAULT_CONFIG, save_config

        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["telegram"]["enabled"] = True
        save_config(self.paths, config)
        report = health_report(self.paths, include_services=False)
        self.assertIn("telegram", report["checks"])
        telegram_check = report["checks"]["telegram"]
        self.assertTrue(telegram_check["enabled"])
        # No status file → not ok when telegram is enabled
        self.assertFalse(telegram_check["ok"])

    def test_health_report_telegram_disabled_is_ok(self) -> None:
        from claude_starter.config import DEFAULT_CONFIG, save_config

        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["telegram"]["enabled"] = False
        save_config(self.paths, config)
        report = health_report(self.paths, include_services=False)
        telegram_check = report["checks"]["telegram"]
        self.assertTrue(telegram_check["ok"])
        self.assertFalse(telegram_check["enabled"])

    def test_health_report_telegram_ok_when_alive_with_token(self) -> None:
        from claude_starter.config import DEFAULT_CONFIG, save_config

        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["telegram"]["enabled"] = True
        save_config(self.paths, config)
        status = {
            "supervisor_pid": os.getpid(),
            "token_available": True,
            "worker_running": True,
        }
        status_file = self.paths.runtime_dir / "telegram_supervisor.json"
        status_file.write_text(json.dumps(status))
        report = health_report(self.paths, include_services=False)
        self.assertTrue(report["checks"]["telegram"]["ok"])
