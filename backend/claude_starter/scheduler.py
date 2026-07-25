"""Window-based scheduler for Claude Window Starter.

Delegates to windows.py for window calculations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .paths import AppPaths
from .state import load_state
from .windows import get_interval, next_window_after, windows_due as _windows_due


def windows_due(paths: AppPaths, config: dict[str, Any]) -> list[str]:
    """Determine which windows need to be triggered.

    Delegates to windows.py. Returns list of window types that are due.
    """
    state = load_state(paths)
    return _windows_due(config, state)


def next_runs(paths: AppPaths, config: dict[str, Any]) -> dict[str, datetime]:
    """Get the next scheduled run time for each window.

    Returns dict mapping window type to next run datetime (UTC).
    """
    state = load_state(paths)
    result: dict[str, datetime] = {}
    windows_config = config.get("windows", {})

    for wtype in ("five_hour", "weekly"):
        w = windows_config.get(wtype, {})

        # Skip if disabled or no anchor
        if not w.get("enabled") or not w.get("anchor_iso"):
            continue

        next_run = state.get(f"{wtype}_next_run_at")
        if next_run:
            try:
                result[wtype] = datetime.fromisoformat(next_run)
                continue
            except ValueError:
                pass

        # If no next_run stored, compute from anchor
        try:
            anchor = datetime.fromisoformat(w["anchor_iso"]).astimezone(timezone.utc)
            interval = get_interval(w)
            result[wtype] = next_window_after(anchor, interval, datetime.now(timezone.utc))
        except (ValueError, KeyError):
            pass

    return result
