from __future__ import annotations

import os
import platform
import shutil
import sys
from typing import Any

from .claude import discover_claude
from .config import load_config
from .errors import AppError, ErrorCode
from .io_utils import read_json
from .paths import AppPaths
from .state import load_state

SUPPORTED_ARCHES = {"arm64", "aarch64", "x86_64", "amd64"}


def _background_status(paths: AppPaths) -> dict[str, Any]:
    value = read_json(paths.runtime_dir / "background.json", {})
    return value if isinstance(value, dict) else {}


def health_report(paths: AppPaths, *, include_services: bool = True) -> dict[str, Any]:
    paths.ensure()
    config = load_config(paths, create=True)
    state = load_state(paths)
    capabilities = discover_claude()
    operating_system = platform.system()
    architecture = platform.machine().lower()
    disk = shutil.disk_usage(paths.base)
    checks: dict[str, Any] = {
        "operating_system": {"ok": operating_system == "Darwin", "value": operating_system},
        "architecture": {"ok": architecture in SUPPORTED_ARCHES, "value": architecture},
        "python": {
            "ok": (3, 10) <= sys.version_info[:2] <= (3, 13),
            "value": platform.python_version(),
        },
        "disk": {"ok": disk.free >= 200 * 1024 * 1024, "free_bytes": disk.free},
        "config": {"ok": True, "schema_version": config["schema_version"]},
        "state": {"ok": state.get("schema_version") == 3},
        "claude": {"ok": capabilities.executable is not None, **capabilities.public_dict()},
        "background": {"ok": True, **_background_status(paths)},
    }
    if include_services:
        checks["services"] = service_status()
    ok = all(item.get("ok", True) for item in checks.values() if isinstance(item, dict))
    return {"ok": ok, "checks": checks}


def service_status() -> dict[str, Any]:
    """Return launchd availability without changing any jobs."""
    launchctl = shutil.which("launchctl")
    if not launchctl:
        return {"ok": True, "available": False, "jobs": {}}
    jobs: dict[str, Any] = {}
    for label in (
        "com.claude-window-starter.background",
        "com.claude-window-starter.telegram",
    ):
        import subprocess

        process = subprocess.run(
            [launchctl, "print", f"gui/{os.getuid()}/{label}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            shell=False,
        )
        jobs[label] = {"active": process.returncode == 0}
    return {"ok": True, "available": True, "jobs": jobs}


def diagnose(paths: AppPaths) -> dict[str, Any]:
    report = health_report(paths)
    architecture = platform.machine().lower()
    if platform.system() != "Darwin":
        raise AppError(ErrorCode.UNSUPPORTED_OS, "Claude Window Starter 2 requires macOS")
    if architecture not in SUPPORTED_ARCHES:
        raise AppError(ErrorCode.UNSUPPORTED_ARCH, f"Unsupported architecture: {architecture}")
    report["environment"] = {
        "operating_system": platform.platform(),
        "machine": architecture,
        "uname": list(platform.uname()),
    }
    return report
