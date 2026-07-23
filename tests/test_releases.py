from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from claude_starter.errors import AppError, ErrorCode
from claude_starter.paths import AppPaths
from claude_starter.releases import ReleaseManager


class LocalReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temporary.name))
        self.paths.ensure()
        self.manager = ReleaseManager(self.paths)
        self.first = self._release("20260723T080000Z-first")
        self.second = self._release("20260723T090000Z-second")
        self.paths.current.symlink_to(self.second)
        self.paths.previous.symlink_to(self.first)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _release(self, name: str) -> Path:
        directory = self.paths.releases / name
        directory.mkdir()
        (directory / "release.json").write_text(
            json.dumps({"schema_version": 2, "healthy": True}), encoding="utf-8"
        )
        return directory

    def test_rollback_switches_current_and_previous_atomically(self) -> None:
        result = self.manager.rollback()
        self.assertEqual(result["release"], self.first.name)
        self.assertEqual(self.paths.current.resolve(), self.first.resolve())
        self.assertEqual(self.paths.previous.resolve(), self.second.resolve())

    def test_rollback_rejects_path_escape(self) -> None:
        outside = self.paths.base / "outside"
        outside.mkdir()
        (outside / "release.json").write_text(
            json.dumps({"schema_version": 2, "healthy": True}), encoding="utf-8"
        )
        with self.assertRaises(AppError) as context:
            self.manager.rollback("../outside")
        self.assertEqual(context.exception.code, ErrorCode.INVALID_RELEASE)

    def test_cleanup_keeps_active_and_fallback(self) -> None:
        extra = self._release("20260723T070000Z-extra")
        self.manager.cleanup(retain=1)
        self.assertFalse(extra.exists())
        self.assertTrue(self.first.exists())
        self.assertTrue(self.second.exists())


if __name__ == "__main__":
    unittest.main()
