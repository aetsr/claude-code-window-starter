from __future__ import annotations

import json
import plistlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter.errors import AppError
from claude_starter.installation import APP_NAME, LABELS, Installer, SystemServices
from claude_starter.paths import AppPaths


class FakeServices(SystemServices):
    def __init__(self, paths: AppPaths, app: Path, agents: Path) -> None:
        super().__init__(paths, app, agents)
        self.active: set[str] = set()
        self.events: list[str] = []
        self.fail_start = False
        self.fail_verify = False
        self.fail_check = False

    def loaded(self, label: str) -> bool:
        return label in self.active

    def stop(self) -> None:
        self.events.append("stop")
        self.active.clear()

    def start(self, labels: list[str]) -> None:
        self.events.append("start")
        self.active.update(labels)
        if self.fail_start:
            self.fail_start = False
            raise RuntimeError("simulated partial bootstrap failure")

    def verify(self) -> None:
        self.events.append("verify")
        if self.fail_verify:
            raise RuntimeError("simulated post-install health failure")

    def check_release(self, release: Path) -> None:
        self.events.append("check")
        if self.fail_check:
            raise RuntimeError("simulated invalid candidate")


class InstallationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.paths = AppPaths(self.root / "App Support & Data")
        self.paths.ensure()
        self.app = self.root / "Applications" / APP_NAME
        self.agents = self.root / "LaunchAgents"
        self.services = FakeServices(self.paths, self.app, self.agents)
        self.installer = Installer(self.paths, self.app, self.agents, self.services)
        self.first = self.release("first")
        self.second = self.release("second")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def release(self, name: str) -> Path:
        target = self.paths.releases / name
        (target / "app" / APP_NAME).mkdir(parents=True)
        (target / "app" / APP_NAME / "version").write_text(name)
        source = Path(__file__).resolve().parents[1]
        shutil.copytree(source / "launchd", target / "launchd")
        shutil.copy2(source / "config/config.example.json", target / "config.example.json")
        (target / "release.json").write_text(
            json.dumps(
                {
                    "complete_release": True,
                    "healthy": False,
                    "app_destination": str(self.app),
                    "agent_directory": str(self.agents),
                }
            )
        )
        return target

    def test_fresh_install_uses_complete_app_and_xml_safe_paths(self) -> None:
        self.installer.activate(self.first)
        self.assertEqual((self.app / "version").read_text(), "first")
        self.assertEqual(self.paths.current.resolve(), self.first)
        self.assertEqual(self.services.active, set(LABELS))
        self.assertTrue(json.loads((self.first / "release.json").read_text())["healthy"])
        for label in LABELS:
            value = plistlib.loads((self.agents / f"{label}.plist").read_bytes())
            self.assertEqual(value["Label"], label)
            self.assertNotIn("@@", str(value))
        self.assertIn(str(self.paths.base), str(value))
        self.assertFalse(self.installer.journal.exists())

    def test_upgrade_and_rollback_switch_app_backend_and_services_together(self) -> None:
        self.installer.activate(self.first)
        self.paths.config_file.write_text('{"preserved": true}')
        self.installer.activate(self.second)
        self.assertEqual((self.app / "version").read_text(), "second")
        self.assertEqual(self.paths.previous.resolve(), self.first)
        self.installer.activate(self.first)
        self.assertEqual((self.app / "version").read_text(), "first")
        self.assertEqual(self.paths.current.resolve(), self.first)
        self.assertEqual(self.paths.previous.resolve(), self.second)
        self.assertEqual(self.paths.config_file.read_text(), '{"preserved": true}')
        self.assertEqual(self.services.active, set(LABELS))

    def test_bad_candidate_does_not_stop_running_app(self) -> None:
        self.installer.activate(self.first)
        self.services.events.clear()
        self.services.fail_check = True
        with self.assertRaises(RuntimeError):
            self.installer.activate(self.second)
        self.assertNotIn("stop", self.services.events)
        self.assertEqual(self.paths.current.resolve(), self.first)

    def test_partial_bootstrap_failure_restores_app_links_config_and_jobs(self) -> None:
        self.installer.activate(self.first)
        before = self.paths.config_file.read_bytes()
        old_plists = {p.name: p.read_bytes() for p in self.agents.glob("*.plist")}
        self.services.fail_start = True
        with self.assertRaises(RuntimeError):
            self.installer.activate(self.second)
        self.assertEqual((self.app / "version").read_text(), "first")
        self.assertEqual(self.paths.current.resolve(), self.first)
        self.assertEqual(self.paths.config_file.read_bytes(), before)
        self.assertEqual(old_plists, {p.name: p.read_bytes() for p in self.agents.glob("*.plist")})
        self.assertEqual(self.services.active, set(LABELS))
        self.assertFalse(self.installer.journal.exists())
        self.assertFalse(json.loads((self.second / "release.json").read_text())["healthy"])

    def test_failed_first_install_leaves_no_active_app_jobs_or_config(self) -> None:
        self.services.fail_verify = True
        with self.assertRaises(RuntimeError):
            self.installer.activate(self.first)
        self.assertFalse(self.app.exists())
        self.assertFalse(self.paths.current.exists())
        self.assertFalse(self.paths.config_file.exists())
        self.assertFalse(self.services.active)
        self.assertFalse(list(self.agents.glob("*.plist")))

    def test_pending_journal_is_recovered_before_next_activation(self) -> None:
        self.installer.activate(self.first)
        self.services.fail_verify = True
        with mock.patch.object(self.installer, "_restore", side_effect=RuntimeError("interrupted")):
            with self.assertRaises(RuntimeError):
                self.installer.activate(self.second)
        self.assertTrue(self.installer.journal.exists())
        self.services.fail_verify = False
        self.installer.activate(self.first)
        self.assertEqual((self.app / "version").read_text(), "first")
        self.assertFalse(self.installer.journal.exists())

    def test_release_path_escape_and_legacy_release_rejected(self) -> None:
        with self.assertRaises(AppError):
            self.installer.activate(self.root)
        (self.first / "release.json").write_text('{"healthy": true}')
        with self.assertRaises(AppError):
            self.installer.activate(self.first)
        self.assertNotIn("stop", self.services.events)

    def test_symlinked_managed_config_is_not_overwritten(self) -> None:
        outside = self.root / "private-file"
        outside.write_text("keep")
        self.paths.config_file.symlink_to(outside)
        with self.assertRaises(AppError):
            self.installer.activate(self.first)
        self.assertEqual(outside.read_text(), "keep")
        self.assertNotIn("stop", self.services.events)
