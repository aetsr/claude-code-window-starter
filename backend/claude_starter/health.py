from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .claude import discover_claude
from .config import load_config
from .errors import AppError, ErrorCode
from .paths import AppPaths
from .state import load_state

SUPPORTED_ARCHES = {"arm64", "aarch64", "x86_64", "amd64"}


def _credential_status(paths: AppPaths, name: str) -> dict[str, Any]:
    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    candidates = [paths.secrets_dir / name, paths.secrets_dir / f"{name}.cred"]
    if directory:
        candidates.insert(0, Path(directory) / name)
    for candidate in candidates:
        try:
            mode = candidate.stat().st_mode & 0o777
            if candidate.is_file() and candidate.stat().st_size > 0:
                return {"configured": True, "permissions_secure": mode & 0o077 == 0}
        except OSError:
            continue
    return {"configured": False, "permissions_secure": False}


def health_report(paths: AppPaths, *, include_services: bool = True) -> dict[str, Any]:
    paths.ensure()
    config = load_config(paths, create=True)
    state = load_state(paths)
    capabilities = discover_claude()
    architecture = platform.machine().lower()
    disk = shutil.disk_usage(paths.base)
    checks: dict[str, Any] = {
        "architecture": {"ok": architecture in SUPPORTED_ARCHES, "value": architecture},
        "python": {
            "ok": (3, 10) <= sys.version_info[:2] <= (3, 13),
            "value": platform.python_version(),
        },
        "disk": {"ok": disk.free >= 200 * 1024 * 1024, "free_bytes": disk.free},
        "config": {"ok": True, "schema_version": config["schema_version"]},
        "state": {"ok": state.get("schema_version") == 1},
        "claude": {"ok": capabilities.executable is not None, **capabilities.public_dict()},
        "oauth_credential": _credential_status(paths, "claude_oauth_token"),
        "telegram_credential": _credential_status(paths, "telegram_token"),
    }
    if include_services:
        checks["services"] = service_status()
    ok = all(item.get("ok", True) for item in checks.values() if isinstance(item, dict))
    return {"ok": ok, "checks": checks}


def service_status() -> dict[str, Any]:
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return {"ok": True, "available": False, "units": {}}
    units = {}
    for unit in (
        "claude-window-starter-run.timer",
        "claude-window-starter-telegram.service",
        "claude-window-starter-update-check.timer",
    ):
        process = subprocess.run(
            [systemctl, "--user", "show", unit, "--property=ActiveState,SubState", "--output=json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
        value: Any = {"active": False}
        if process.returncode == 0:
            try:
                value = json.loads(process.stdout)
            except json.JSONDecodeError:
                value = {"active": "ActiveState=active" in process.stdout}
        units[unit] = value
    return {"ok": True, "available": True, "units": units}


def diagnose(paths: AppPaths) -> dict[str, Any]:
    report = health_report(paths)
    architecture = platform.machine().lower()
    if architecture not in SUPPORTED_ARCHES:
        raise AppError(ErrorCode.UNSUPPORTED_ARCH, f"Unsupported architecture: {architecture}")
    report["environment"] = {
        "operating_system": platform.platform(),
        "machine": architecture,
        "uname": list(platform.uname()),
    }
    return report
