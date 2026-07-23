from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .config import local_now
from .paths import AppPaths
from .state import load_state


def scheduled_time(config: dict[str, Any], day: datetime) -> datetime:
    hour, minute = (int(part) for part in config["schedule_time"].split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(config["timezone"]))


def next_run(config: dict[str, Any], now: datetime | None = None) -> datetime:
    current = now or local_now(config)
    candidate = scheduled_time(config, current)
    if candidate <= current:
        candidate = scheduled_time(config, current + timedelta(days=1))
    return candidate


def catch_up_due(paths: AppPaths, config: dict[str, Any], now: datetime | None = None) -> bool:
    if not config["enabled"] or not config["allow_catch_up"]:
        return False
    current = now or local_now(config)
    if current < scheduled_time(config, current):
        return False
    state = load_state(paths)
    return state.get("last_automatic_date") != current.date().isoformat()
