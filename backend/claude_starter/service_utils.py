from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .errors import AppError, ErrorCode


def service_action(target: str, action: str, timeout: int = 20) -> dict[str, Any]:
    """Manage a launchd service (start, stop, restart, status)."""
    launchctl = "/bin/launchctl"
    if not Path(launchctl).exists():
        raise AppError(ErrorCode.LAUNCHD_FAILED, "launchctl is unavailable")
    label = f"com.claude-window-starter.{target}"
    domain = f"gui/{os.getuid()}"
    if action == "status":
        argv = [launchctl, "print", f"{domain}/{label}"]
    elif action == "stop":
        argv = [launchctl, "kill", "SIGTERM", f"{domain}/{label}"]
    elif action == "start":
        argv = [launchctl, "kickstart", f"{domain}/{label}"]
    else:
        argv = [launchctl, "kickstart", "-k", f"{domain}/{label}"]
    process = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=False, shell=False
    )
    if process.returncode != 0:
        raise AppError(ErrorCode.LAUNCHD_FAILED, f"Unable to {action} {target} service")
    return {"label": label, "action": action, "output": process.stdout.strip()}


def kickstart_local_job(trigger: str) -> None:
    """Kickstart a one-shot launchd job for the given trigger (dry, telegram)."""
    launchctl = "/bin/launchctl"
    domain = f"gui/{os.getuid()}"
    process = subprocess.run(
        [launchctl, "kickstart", "-k", f"{domain}/com.claude-window-starter.run-{trigger}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        shell=False,
    )
    if process.returncode != 0:
        raise AppError(ErrorCode.LAUNCHD_FAILED, "Unable to start local run service")


def send_mac_notification(title: str, body: str) -> None:
    """Send a macOS user notification via osascript (best-effort)."""
    safe_title = title.replace('"', '\\"')
    safe_body = body.replace('"', '\\"').replace("\n", " ")[:200]
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{safe_body}" with title "{safe_title}"'],
            timeout=5, check=False, capture_output=True,
        )
    except Exception:
        pass