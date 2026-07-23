from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import AppError, ErrorCode
from .locks import FileLock
from .paths import AppPaths
from .state import update_state


def _atomic_symlink(target: Path, link: Path) -> None:
    temporary = link.parent / f".{link.name}.{os.getpid()}.tmp"
    try:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        temporary.symlink_to(target)
        os.replace(temporary, link)
    except OSError as exc:
        raise AppError(ErrorCode.SYMLINK_SWITCH_FAILED, "Unable to switch local release") from exc


class ReleaseManager:
    """Manage immutable releases installed on this Mac."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        paths.ensure()

    def active_manifest(self) -> dict[str, Any] | None:
        try:
            path = self.paths.current.resolve(strict=True) / "release.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, RuntimeError, json.JSONDecodeError):
            return None

    def list_releases(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for release in sorted((p for p in self.paths.releases.iterdir() if p.is_dir()), reverse=True):
            try:
                manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
                if isinstance(manifest, dict):
                    result.append({"release": release.name, **manifest})
            except (OSError, json.JSONDecodeError):
                continue
        return result

    def rollback(self, release_name: str | None = None) -> dict[str, Any]:
        with FileLock(self.paths.run_lock, timeout=15, error_code=ErrorCode.ALREADY_RUNNING):
            try:
                current = self.paths.current.resolve(strict=True)
                target = self.paths.releases / release_name if release_name else self.paths.previous.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise AppError(ErrorCode.NO_HEALTHY_PREVIOUS_RELEASE) from exc
            releases_root = self.paths.releases.resolve()
            try:
                target = target.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise AppError(ErrorCode.NO_HEALTHY_PREVIOUS_RELEASE) from exc
            if target.parent != releases_root:
                raise AppError(ErrorCode.INVALID_RELEASE, "Release must be inside the local releases directory")
            if not target.is_dir() or not (target / "release.json").is_file():
                raise AppError(ErrorCode.NO_HEALTHY_PREVIOUS_RELEASE)
            try:
                manifest = json.loads((target / "release.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise AppError(ErrorCode.INVALID_RELEASE) from exc
            if not isinstance(manifest, dict) or manifest.get("healthy") is not True:
                raise AppError(ErrorCode.INVALID_RELEASE, "Only a healthy local release can be activated")
            _atomic_symlink(current, self.paths.previous)
            _atomic_symlink(target, self.paths.current)
            update_state(
                self.paths,
                lambda state: state.__setitem__(
                    "last_maintenance",
                    {"action": "rollback", "release": target.name, "time": datetime.now(timezone.utc).isoformat()},
                ),
            )
            return {"status": "success", "release": target.name, "previous": current.name}

    def cleanup(self, retain: int = 5) -> None:
        retain = max(1, int(retain))
        releases = sorted((p for p in self.paths.releases.iterdir() if p.is_dir()), reverse=True)
        protected = {p.resolve() for p in (self.paths.current, self.paths.previous) if p.exists()}
        for release in releases[retain:]:
            if release.resolve() not in protected:
                shutil.rmtree(release)
