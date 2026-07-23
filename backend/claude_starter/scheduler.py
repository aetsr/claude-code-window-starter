from __future__ import annotations

from datetime import datetime, timedelta, timezone
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


def due_date(config: dict[str, Any], now: datetime | None = None) -> str | None:
    current = now or local_now(config)
    if current < scheduled_time(config, current):
        return None
    return current.date().isoformat()


def automatic_due(paths: AppPaths, config: dict[str, Any], now: datetime | None = None) -> bool:
    if not config["enabled"]:
        return False
    state = load_state(paths)
    pending = state.get("pending_automatic")
    if pending:
        retry_at = state.get("next_automatic_retry_at")
        if isinstance(retry_at, str):
            try:
                if datetime.now(timezone.utc) < datetime.fromisoformat(retry_at):
                    return False
            except ValueError:
                pass
        return True
    date = due_date(config, now)
    return bool(
        config["allow_catch_up"]
        and date
        and state.get("automatic_blocked_date") != date
        and (not config["prevent_duplicate_daily_run"] or state.get("last_automatic_date") != date)
    )


def mark_pending(paths: AppPaths, config: dict[str, Any], reason: str) -> None:
    current = local_now(config)
    date = due_date(config, current) or current.date().isoformat()

    from .state import update_state

    def update(state: dict[str, Any]) -> None:
        pending = state.get("pending_automatic")
        attempts = int(pending.get("attempts", 0)) + 1 if isinstance(pending, dict) else 1
        delay = min(900, 30 * (2 ** min(attempts - 1, 5)))
        if not isinstance(pending, dict):
            state["pending_automatic"] = {
                "scheduled_date": date,
                "scheduled_at": scheduled_time(config, current).isoformat(),
                "reason": reason,
                "first_seen_at": current.isoformat(),
                "attempts": attempts,
            }
        else:
            pending["reason"] = reason
            pending["attempts"] = attempts
        state["next_automatic_retry_at"] = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()

    update_state(paths, update)


def clear_pending(paths: AppPaths) -> None:
    from .state import update_state

    def clear(state: dict[str, Any]) -> None:
        state["pending_automatic"] = None
        state["next_automatic_retry_at"] = None

    update_state(paths, clear)


def catch_up_due(paths: AppPaths, config: dict[str, Any], now: datetime | None = None) -> bool:
    return automatic_due(paths, config, now)
