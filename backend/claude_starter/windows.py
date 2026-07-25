"""Window scheduling engine for Claude Window Starter.

Manages two types of usage windows:
- five_hour: recurring 5h3m windows (configurable interval)
- weekly: recurring 7-day windows

All datetime computations use UTC for reliability across timezone/DST boundaries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

WINDOW_FIVE_HOUR = "five_hour"
WINDOW_WEEKLY = "weekly"


def next_window_after(
    anchor: datetime, interval: timedelta, now: datetime
) -> datetime:
    """Calculate the next window start time after 'now'.

    Args:
        anchor: Reference window start time (UTC)
        interval: Recurrence interval (timedelta)
        now: Current time (UTC)

    Returns:
        Next window start datetime (UTC)
    """
    if now < anchor:
        return anchor
    elapsed = now - anchor
    n = int(elapsed / interval)
    return anchor + (n + 1) * interval


def current_window_start(
    anchor: datetime, interval: timedelta, now: datetime
) -> datetime:
    """Calculate the start time of the currently active window.

    Args:
        anchor: Reference window start time (UTC)
        interval: Recurrence interval (timedelta)
        now: Current time (UTC)

    Returns:
        Current window start datetime (UTC)
    """
    if now < anchor:
        return anchor
    elapsed = now - anchor
    n = int(elapsed / interval)
    return anchor + n * interval


def get_interval(config_window: dict[str, Any]) -> timedelta:
    """Extract interval from window config dict.

    Args:
        config_window: Window configuration dict with 'interval_minutes' key

    Returns:
        Interval as timedelta
    """
    minutes = int(config_window.get("interval_minutes", 0))
    return timedelta(minutes=minutes)


def windows_due(
    config: dict[str, Any], state: dict[str, Any], now: datetime | None = None
) -> list[str]:
    """Determine which windows need to be triggered.

    A window is due if:
    - It is enabled and has an anchor time configured
    - Either: no previous run stored, OR current time >= next_run_at

    Args:
        config: Configuration dict with 'windows' section
        state: State dict with 'five_hour_next_run_at', 'weekly_next_run_at', etc.
        now: Current time (defaults to UTC now)

    Returns:
        List of window type strings that are due ("five_hour", "weekly")
    """
    if now is None:
        now = datetime.now(timezone.utc)

    due = []
    windows_config = config.get("windows", {})

    for wtype in (WINDOW_FIVE_HOUR, WINDOW_WEEKLY):
        w = windows_config.get(wtype, {})

        # Skip if disabled or no anchor configured
        if not w.get("enabled") or not w.get("anchor_iso"):
            continue

        next_run = state.get(f"{wtype}_next_run_at")

        # No previous run: check if we're past the anchor
        if next_run is None:
            try:
                anchor = datetime.fromisoformat(w["anchor_iso"]).astimezone(
                    timezone.utc
                )
                if now >= anchor:
                    due.append(wtype)
            except ValueError:
                pass
        else:
            # Check if current time >= scheduled next run
            try:
                if now >= datetime.fromisoformat(next_run):
                    due.append(wtype)
            except ValueError:
                pass

    return due


def advance_window(
    wtype: str, config: dict[str, Any], now: datetime | None = None
) -> datetime:
    """Calculate the next run time after a successful trigger.

    Args:
        wtype: Window type ("five_hour" or "weekly")
        config: Configuration dict
        now: Current time (defaults to UTC now)

    Returns:
        Next scheduled run time (UTC)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    windows_config = config.get("windows", {})
    w = windows_config.get(wtype, {})

    anchor_iso = w.get("anchor_iso")
    if not anchor_iso:
        raise ValueError(f"Window {wtype} has no anchor configured")

    anchor = datetime.fromisoformat(anchor_iso).astimezone(timezone.utc)
    interval = get_interval(w)

    return next_window_after(anchor, interval, now)


def format_countdown(target: datetime, now: datetime | None = None) -> str:
    """Format countdown text for display.

    Example outputs:
    - "3g 4s 17dk" (3 days, 4 hours, 17 minutes)
    - "45dk" (45 minutes)
    - "Şimdi" (now or in past)

    Args:
        target: Target datetime (UTC)
        now: Current time (defaults to UTC now)

    Returns:
        Formatted countdown string
    """
    if now is None:
        now = datetime.now(timezone.utc)

    delta = target - now
    if delta.total_seconds() <= 0:
        return "Şimdi"

    total_seconds = int(delta.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    parts = []
    if days:
        parts.append(f"{days}g")
    if hours:
        parts.append(f"{hours}s")
    if minutes or not parts:
        parts.append(f"{minutes}dk")

    return " ".join(parts)
