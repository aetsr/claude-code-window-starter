from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .errors import AppError, ErrorCode
from .paths import AppPaths


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
        for release in sorted(
            (p for p in self.paths.releases.iterdir() if p.is_dir()), reverse=True
        ):
            try:
                manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
                if isinstance(manifest, dict):
                    result.append({"release": release.name, **manifest})
            except (OSError, json.JSONDecodeError):
                continue
        return result

    def rollback(self, release_name: str | None = None) -> dict[str, Any]:
        from .installation import Installer

        try:
            target = self.paths.releases / release_name if release_name else self.paths.previous
            target = target.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise AppError(ErrorCode.NO_HEALTHY_PREVIOUS_RELEASE) from exc
        if target.parent != self.paths.releases.resolve():
            raise AppError(ErrorCode.INVALID_RELEASE, "Release must be inside releases")
        try:
            manifest = json.loads((target / "release.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AppError(ErrorCode.INVALID_RELEASE) from exc
        if not isinstance(manifest, dict) or manifest.get("healthy") is not True:
            raise AppError(ErrorCode.INVALID_RELEASE, "Only a healthy release can be activated")
        if not manifest.get("complete_release"):
            raise AppError(
                ErrorCode.INVALID_RELEASE,
                "Legacy backend-only release: reinstall its source for a full downgrade",
            )
        installer = Installer(
            self.paths, Path(manifest["app_destination"]), Path(manifest["agent_directory"])
        )
        return installer.activate(target)

    def cleanup(self, retain: int = 5) -> None:
        retain = max(1, int(retain))
        releases = sorted((p for p in self.paths.releases.iterdir() if p.is_dir()), reverse=True)
        protected = {p.resolve() for p in (self.paths.current, self.paths.previous) if p.exists()}
        for release in releases[retain:]:
            if release.resolve() not in protected:
                shutil.rmtree(release)
