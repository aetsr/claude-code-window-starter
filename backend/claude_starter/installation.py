"""Stage and activate complete local releases with recoverable installation state.

Only the SystemServices adapter touches macOS processes. Tests exercise real
filesystem transactions with a fake service adapter and never touch user jobs.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from . import __version__
from .errors import AppError, ErrorCode
from .io_utils import atomic_write_bytes, atomic_write_json, read_json
from .locks import FileLock
from .paths import AppPaths

APP_NAME = "Claude Window Starter.app"
LABELS = tuple(
    f"com.claude-window-starter.{suffix}"
    for suffix in ("background", "telegram", "run-dry", "run-telegram")
)
LEGACY_LABEL = "com.claude-window-starter"


def run_checked(argv: list[str]) -> str:
    result = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
    )
    if result.returncode:
        # Do not forward arbitrary child output (which may contain account data).
        raise AppError(ErrorCode.INVALID_RELEASE, f"Release check failed: {Path(argv[0]).name}")
    return result.stdout


class SystemServices:
    def __init__(self, paths: AppPaths, app: Path, agents: Path) -> None:
        self.paths, self.app, self.agents = paths, app, agents
        self.domain = f"gui/{os.getuid()}"

    def loaded(self, label: str) -> bool:
        result = subprocess.run(
            ["/bin/launchctl", "print", f"{self.domain}/{label}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return result.returncode == 0

    def stop(self) -> None:
        for label in (*LABELS, LEGACY_LABEL):
            if self.loaded(label):
                run_checked(["/bin/launchctl", "bootout", f"{self.domain}/{label}"])
        # Only stop this installation's exact app/helper executable paths.
        listing = run_checked(["/bin/ps", "-axo", "pid=,command="])
        executables = (
            str(self.app / "Contents/MacOS/ClaudeWindowStarter"),
            str(self.app / "Contents/Helpers/ClaudeWindowStarterAgent"),
        )
        for line in listing.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and any(
                parts[1] == exe or parts[1].startswith(exe + " ") for exe in executables
            ):
                self._terminate(int(parts[0]))
        # A legacy worker may outlive its launchd job. Verify its full task
        # identity before terminating the PID from its lock file.
        lock = self.paths.bot_lock
        try:
            pid = int(lock.read_text().strip())
        except (OSError, ValueError):
            return
        if pid <= 1 or pid == os.getpid():
            return
        for line in listing.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and parts[0] == str(pid):
                command = f" {parts[1]} "
                if all(
                    value in command
                    for value in (
                        " -m claude_starter ",
                        f" --home {self.paths.base} ",
                        " telegram-bot ",
                    )
                ):
                    self._terminate(pid)

    @staticmethod
    def _terminate(pid: int) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        raise AppError(ErrorCode.INVALID_RELEASE, "An old app process did not stop safely")

    def start(self, labels: list[str]) -> None:
        for label in labels:
            run_checked(
                ["/bin/launchctl", "bootstrap", self.domain, str(self.agents / f"{label}.plist")]
            )

    def verify(self) -> None:
        run_checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(self.app)])
        for label in LABELS[:2]:
            if not self.loaded(label):
                raise AppError(ErrorCode.INVALID_RELEASE, "A background service did not load")

    def check_release(self, release: Path) -> None:
        app = release / "app" / APP_NAME
        run_checked(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)])
        # No account login or network request is needed to validate installation.
        with tempfile.TemporaryDirectory(prefix="cws-health-") as temporary:
            check = AppPaths(Path(temporary))
            check.ensure()
            for source, destination in (
                (self.paths.config_file, check.config_file),
                (self.paths.state_file, check.state_file),
            ):
                if source.exists():
                    shutil.copy2(source, destination)
            python = str(release / ".venv/bin/python")
            version = json.loads(
                run_checked(
                    [
                        python,
                        "-I",
                        "-m",
                        "claude_starter",
                        "--home",
                        temporary,
                        "--json",
                        "version",
                    ]
                )
            )["data"]["application_version"]
            manifest = read_json(release / "release.json")
            if version != manifest["application_version"]:
                raise AppError(ErrorCode.INVALID_RELEASE, "Backend and release versions differ")
            run_checked(
                [
                    python,
                    "-I",
                    "-m",
                    "claude_starter",
                    "--home",
                    temporary,
                    "--json",
                    "config",
                    "get",
                ]
            )


class Installer:
    def __init__(
        self, paths: AppPaths, app: Path, agents: Path, services: SystemServices | None = None
    ) -> None:
        if app.name != APP_NAME or app.is_symlink():
            raise AppError(ErrorCode.INVALID_RELEASE, "Expected a non-symlink app destination")
        self.paths, self.app, self.agents = paths, app.absolute(), agents.absolute()
        self.services = services or SystemServices(paths, self.app, self.agents)
        self.journal = paths.base / "install-transaction.json"

    def stage(self, source: Path, app: Path) -> Path:
        """Create a complete candidate without modifying the running installation."""
        self.paths.ensure()
        release = (
            self.paths.releases
            / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
        )
        release.mkdir(mode=0o700)
        shutil.copytree(
            source / "backend",
            release / "backend",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        shutil.copytree(app, release / "app" / APP_NAME)
        shutil.copytree(source / "launchd", release / "launchd")
        shutil.copy2(source / "config/config.example.json", release / "config.example.json")
        run_checked([sys.executable, "-I", "-m", "venv", "--without-pip", str(release / ".venv")])
        python = str(release / ".venv/bin/python")
        site = Path(
            run_checked(
                [python, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"]
            ).strip()
        )
        atomic_write_bytes(
            site / "claude_window_starter.pth", (str(release / "backend") + "\n").encode()
        )
        app_info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        if app_info["CFBundleShortVersionString"] != __version__:
            raise AppError(ErrorCode.INVALID_RELEASE, "App and installer versions differ")
        atomic_write_json(
            release / "release.json",
            {
                "schema_version": 3,
                "application_version": __version__,
                "healthy": False,
                "install_result": "staged",
                "app_destination": str(self.app),
                "agent_directory": str(self.agents),
                "complete_release": True,
            },
        )
        self.services.check_release(release)
        return release

    def _target(self, release: Path) -> Path:
        release = release.resolve(strict=True)
        if release.parent != self.paths.releases.resolve():
            raise AppError(ErrorCode.INVALID_RELEASE, "Release must be inside releases")
        manifest = read_json(release / "release.json")
        if not manifest.get("complete_release") or not (release / "app" / APP_NAME).is_dir():
            raise AppError(
                ErrorCode.INVALID_RELEASE,
                "Legacy backend-only release: reinstall its source for a full downgrade",
            )
        if manifest.get("app_destination") != str(self.app):
            raise AppError(ErrorCode.INVALID_RELEASE, "Release belongs to another app destination")
        return release

    def _plist(self, template: Path) -> bytes:
        replacements = {
            "@@PYTHON@@": str(self.paths.current / ".venv/bin/python"),
            "@@HOME@@": str(self.paths.base),
            "@@PATH@@": (
                f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:"
                "/usr/bin:/bin:/usr/sbin:/sbin"
            ),
            "@@AGENT@@": str(self.app / "Contents/Helpers/ClaudeWindowStarterAgent"),
        }

        def replace(value: Any) -> Any:
            if isinstance(value, str):
                for old, new in replacements.items():
                    value = value.replace(old, new)
                return value
            if isinstance(value, list):
                return [replace(item) for item in value]
            if isinstance(value, dict):
                return {key: replace(item) for key, item in value.items()}
            return value

        return plistlib.dumps(replace(plistlib.loads(template.read_bytes())))

    @staticmethod
    def _link(path: Path, target: str | None) -> None:
        if target is None:
            path.unlink(missing_ok=True)
            return
        temporary = path.with_name(f".{path.name}-{uuid.uuid4().hex}")
        temporary.symlink_to(target)
        os.replace(temporary, path)

    def _restore(self, journal: dict[str, Any]) -> None:
        self.services.stop()
        backup = Path(journal["backup"])
        old_app = Path(journal["old_app"])
        # Old bundle moves out before replacement. If it exists it is always
        # the recovery source, including after an interrupted previous recovery.
        if old_app.exists():
            if self.app.exists():
                shutil.rmtree(self.app)
            shutil.copytree(old_app, self.app)
        elif not journal["had_app"] and self.app.exists():
            shutil.rmtree(self.app)
        for name, target in journal["links"].items():
            self._link(self.paths.base / name, target)
        for entry in journal["files"]:
            destination = Path(entry["path"])
            saved = backup / entry["name"]
            if saved.exists():
                atomic_write_bytes(destination, saved.read_bytes(), entry["mode"])
            else:
                destination.unlink(missing_ok=True)
        self.services.start(journal["loaded"])
        self.journal.unlink()
        # Keep recovery snapshots for inspection; never overwrite them.

    def activate(self, release: Path) -> dict[str, Any]:
        self.paths.ensure()
        with (
            FileLock(self.paths.runtime_dir / "install.lock", timeout=0),
            FileLock(self.paths.runtime_dir / "schedule.lock", timeout=30),
            FileLock(self.paths.run_lock, timeout=30),
        ):
            if self.journal.exists():
                self._restore(read_json(self.journal))
            release = self._target(release)
            for link in (self.paths.current, self.paths.previous):
                if link.exists() and not link.is_symlink():
                    raise AppError(ErrorCode.INVALID_RELEASE, "Expected managed release symlinks")
            self.services.check_release(release)
            self.app.parent.mkdir(parents=True, exist_ok=True)
            self.agents.mkdir(parents=True, exist_ok=True)
            backup = self.paths.base / "install-backups" / uuid.uuid4().hex
            backup.mkdir(parents=True, mode=0o700)
            staged_app = self.app.with_name(f".{APP_NAME}-{backup.name}.new")
            old_app = self.app.with_name(f".{APP_NAME}-{backup.name}.old")
            shutil.copytree(release / "app" / APP_NAME, staged_app)
            rendered = {
                label: self._plist(release / "launchd" / f"{label}.plist") for label in LABELS
            }
            journal: dict[str, Any] = {
                "backup": str(backup),
                "old_app": str(old_app),
                "had_app": self.app.exists(),
                "links": {
                    name: str((self.paths.base / name).resolve())
                    if (self.paths.base / name).is_symlink()
                    else None
                    for name in ("current", "previous")
                },
                "loaded": [
                    label for label in (*LABELS, LEGACY_LABEL) if self.services.loaded(label)
                ],
                "files": [],
            }
            # Write the recovery journal before the first process or active-file change.
            for index, path in enumerate(
                [
                    self.paths.config_file,
                    self.paths.state_file,
                    *(self.agents / f"{label}.plist" for label in (*LABELS, LEGACY_LABEL)),
                ]
            ):
                if path.is_symlink():
                    raise AppError(ErrorCode.INVALID_RELEASE, "Refusing a symlinked managed file")
                mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
                if path.exists():
                    shutil.copy2(path, backup / str(index))
                journal["files"].append({"path": str(path), "name": str(index), "mode": mode})
            atomic_write_json(self.journal, journal)
            try:
                self.services.stop()
                with FileLock(self.paths.bot_lock, timeout=20):
                    if self.app.exists():
                        os.replace(self.app, old_app)
                    os.replace(staged_app, self.app)
                    if not self.paths.config_file.exists():
                        atomic_write_bytes(
                            self.paths.config_file, (release / "config.example.json").read_bytes()
                        )
                    self._link(self.paths.current, str(release))
                    if journal["links"]["current"]:
                        self._link(self.paths.previous, journal["links"]["current"])
                    for label, data in rendered.items():
                        atomic_write_bytes(self.agents / f"{label}.plist", data, 0o644)
                    (self.agents / f"{LEGACY_LABEL}.plist").unlink(missing_ok=True)
                    self.services.check_release(release)
                self.services.start(list(LABELS))
                self.services.verify()
                manifest = read_json(release / "release.json")
                manifest.update(healthy=True, install_result="verified")
                atomic_write_json(release / "release.json", manifest)
                self.journal.unlink()
            except BaseException:
                self._restore(journal)
                raise
            return {
                "status": "success",
                "release": release.name,
                "previous": journal["links"]["current"],
                "app": str(self.app),
            }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install a complete Claude Code window starter release"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--app-destination", type=Path, default=Path("/Applications") / APP_NAME)
    args = parser.parse_args()
    if sys.platform != "darwin" or not (3, 10) <= sys.version_info[:2] <= (3, 13):
        parser.error("Installation requires macOS and Python 3.10–3.13")
    os.umask(0o077)
    installer = Installer(
        AppPaths.discover(), args.app_destination, Path.home() / "Library/LaunchAgents"
    )
    try:
        release = installer.stage(args.source.resolve(), args.app.resolve())
        result = installer.activate(release)
        print(json.dumps(result))
    except (AppError, OSError) as exc:
        raise SystemExit(f"Installation failed; inspect local install-backups: {exc}") from None


if __name__ == "__main__":
    main()
