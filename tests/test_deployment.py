from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter.config import DEFAULT_CONFIG, save_config
from claude_starter.deployment import ReleaseManager, _atomic_symlink
from claude_starter.errors import AppError, ErrorCode
from claude_starter.paths import AppPaths


class TestReleaseManager(ReleaseManager):
    def _post_health(self, release: Path, config: dict[str, object]) -> None:
        return


class DeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths = AppPaths(self.root / "app")
        self.paths.ensure()
        self.origin = self.root / "origin"
        subprocess.run(["git", "init", "-b", "main", str(self.origin)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(self.origin), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.origin), "config", "user.name", "Test"], check=True)
        (self.origin / "README.md").write_text("safe\n")
        subprocess.run(["git", "-C", str(self.origin), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.origin), "commit", "-m", "initial"], check=True, stdout=subprocess.DEVNULL)
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["deployment"]["repository_url"] = str(self.origin)
        config["deployment"]["protected_branch_confirmed"] = True
        save_config(self.paths, config)
        self.environment = mock.patch.dict(
            os.environ,
            {"CLAUDE_STARTER_ALLOW_LOCAL_GIT": "1", "CLAUDE_STARTER_SKIP_SERVICE_RESTART": "1"},
        )
        self.environment.start()

    def tearDown(self) -> None:
        self.environment.stop()
        self.temporary.cleanup()

    def test_remote_branch_head_is_detected(self) -> None:
        result = ReleaseManager(self.paths).check()
        self.assertTrue(result["update_available"])
        self.assertEqual(len(result["remote_commit_sha"]), 40)

    def test_archive_rejects_secret_path(self) -> None:
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            content = b"SECRET"
            info = tarfile.TarInfo(".env")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
        destination = self.root / "release"
        destination.mkdir()
        with self.assertRaises(AppError) as context:
            ReleaseManager(self.paths)._safe_extract(data.getvalue(), destination)
        self.assertEqual(context.exception.code, ErrorCode.RELEASE_PREPARATION_FAILED)

    def test_atomic_symlink_switch(self) -> None:
        first = self.paths.releases / "first"
        second = self.paths.releases / "second"
        first.mkdir()
        second.mkdir()
        _atomic_symlink(first, self.paths.current)
        self.assertTrue(self.paths.current.resolve().samefile(first))
        _atomic_symlink(second, self.paths.current)
        self.assertTrue(self.paths.current.resolve().samefile(second))

    def test_rollback_accepts_only_healthy_local_release(self) -> None:
        old = self.paths.releases / "old"
        current = self.paths.releases / "current-release"
        old.mkdir()
        current.mkdir()
        (old / "release.json").write_text(json.dumps({"healthy": True, "commit_sha": "a" * 40}))
        (current / "release.json").write_text(json.dumps({"healthy": True, "commit_sha": "b" * 40}))
        _atomic_symlink(current, self.paths.current)
        _atomic_symlink(old, self.paths.previous)
        result = TestReleaseManager(self.paths).rollback()
        self.assertEqual(result["release"], "old")
        self.assertTrue(self.paths.current.resolve().samefile(old))

    @unittest.skipUnless(os.environ.get("ENABLE_LOCAL_DEPLOYMENT_TEST") == "1", "explicit local integration test")
    def test_full_release_apply_from_private_repo_simulation(self) -> None:
        source = self.root / "full-origin"
        project = Path(__file__).resolve().parents[1]
        shutil.copytree(
            project,
            source,
            ignore=shutil.ignore_patterns(".git", ".build", "__pycache__", ".venv", "*.pyc"),
        )
        subprocess.run(["git", "init", "-b", "main", str(source)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "-C", str(source), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(source), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "commit", "-m", "release"], check=True, stdout=subprocess.DEVNULL)
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["deployment"]["repository_url"] = str(source)
        config["deployment"]["protected_branch_confirmed"] = True
        save_config(self.paths, config)
        result = ReleaseManager(self.paths).apply()
        self.assertEqual(result["status"], "success")
        self.assertTrue(ReleaseManager(self.paths).active_manifest()["healthy"])


if __name__ == "__main__":
    unittest.main()
