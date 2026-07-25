from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, TypeGuard

from .errors import AppError
from .io_utils import read_json
from .paths import AppPaths

FIVE_HOURS = timedelta(hours=5)


def _is_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def normalized_rate_limits(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, Any] = {}
    for name in ("five_hour", "seven_day"):
        window = value.get(name)
        if not isinstance(window, dict):
            continue
        used = window.get("used_percentage")
        resets = window.get("resets_at")
        if not _is_number(used) or not 0 <= float(used) <= 100:
            continue
        if not _is_number(resets) or int(resets) <= 0:
            continue
        result[name] = {
            "used_percentage": round(float(used), 2),
            "resets_at": int(resets),
        }
    return result if "five_hour" in result else None


def captured_rate_limits(paths: AppPaths, *, newer_than: float) -> dict[str, Any] | None:
    try:
        value = read_json(paths.usage_status_file, {})
    except AppError:
        return None
    if not isinstance(value, dict):
        return None
    captured_at = value.get("captured_at_epoch")
    if not _is_number(captured_at) or float(captured_at) < newer_than:
        return None
    return normalized_rate_limits(value.get("rate_limits"))


def next_window_time(
    rate_limits: dict[str, Any] | None,
    *,
    completed_at: datetime,
    grace_seconds: int,
) -> tuple[datetime, bool]:
    five_hour = rate_limits.get("five_hour") if rate_limits else None
    resets_at = five_hour.get("resets_at") if isinstance(five_hour, dict) else None
    if _is_number(resets_at):
        candidate = datetime.fromtimestamp(float(resets_at), timezone.utc) + timedelta(
            seconds=grace_seconds
        )
        if candidate > completed_at:
            return candidate, True
    return completed_at + FIVE_HOURS, False
