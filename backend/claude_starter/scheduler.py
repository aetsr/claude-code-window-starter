"""Window-based scheduler for Claude Window Starter.

Delegates to windows.py for window calculations.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .errors import AppError, ErrorCode
from .locks import FileLock
from .paths import AppPaths
from .state import load_state, update_state
from .windows import (
    _parse_iso,
    get_interval,
    next_window_after,
)
from .windows import (
    windows_due as _windows_due,
)


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

        if wtype == "five_hour" and w.get("mode") == "adaptive":
            snapshot = schedule_snapshot(paths, config)
            next_at = snapshot.get("next_action_at")
            if isinstance(next_at, str):
                result[wtype] = _parse_iso(next_at)
            continue

        # Skip if disabled or no anchor
        if not w.get("enabled") or not w.get("anchor_iso"):
            continue

        next_run = state.get(f"{wtype}_next_run_at")
        if next_run:
            try:
                result[wtype] = _parse_iso(next_run)
                continue
            except ValueError:
                pass

        # If no next_run stored, compute from anchor
        try:
            anchor = _parse_iso(w["anchor_iso"]).astimezone(timezone.utc)
            interval = get_interval(w)
            result[wtype] = next_window_after(anchor, interval, datetime.now(timezone.utc))
        except (ValueError, KeyError):
            pass

    return result


def ideal_actions_for_day(config: dict[str, Any], target_date: date) -> list[dict[str, Any]]:
    """Create the balanced, maximum-quota action sequence for one local day."""
    window = config["windows"]["five_hour"]
    if target_date.isoweekday() not in window["active_weekdays"]:
        return []
    zone = ZoneInfo(config["timezone"])
    start_hour, start_minute = (int(part) for part in window["busy_start_local"].split(":"))
    end_hour, end_minute = (int(part) for part in window["busy_end_local"].split(":"))
    busy_start = datetime.combine(target_date, time(start_hour, start_minute), tzinfo=zone)
    busy_end = datetime.combine(target_date, time(end_hour, end_minute), tzinfo=zone)
    # Three hours of lead-in gives the first busy-hours reset useful headroom,
    # while the 303-minute cadence distributes the first/last partial windows.
    local_midnight = datetime.combine(target_date, time.min, tzinfo=zone)
    cursor = max(busy_start - timedelta(hours=3), local_midnight)
    interval = timedelta(minutes=int(window["interval_minutes"]))
    actions: list[dict[str, Any]] = []
    index = 0
    while cursor <= busy_end:
        utc_value = cursor.astimezone(timezone.utc)
        actions.append(
            {
                "id": f"{target_date.isoformat()}-{index}-{utc_value.isoformat()}",
                "scheduled_at": utc_value.isoformat(),
                "kind": "anchor",
                "status": "planned",
                "confidence": "planned",
            }
        )
        cursor += interval
        index += 1
    return actions


def schedule_snapshot(
    paths: AppPaths,
    config: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window = config["windows"]["five_hour"]
    zone = ZoneInfo(config["timezone"])
    local_now = current.astimezone(zone)
    state = load_state(paths)
    observation = _fresh_observation(state.get("usage_observation"), current)
    observed_window = observation.get("limits", {}).get("five_hour") if observation else None

    if not window.get("enabled"):
        status = "disabled"
        today_actions: list[dict[str, Any]] = []
        next_action = None
    elif window.get("mode") != "adaptive":
        status = "manual_fallback"
        today_actions = []
        next_action = state.get("five_hour_next_run_at")
    else:
        today_actions = _actions_with_results(
            ideal_actions_for_day(config, local_now.date()), state
        )
        plan = state.get("adaptive_plan")
        if (
            isinstance(plan, dict)
            and plan.get("date") == local_now.date().isoformat()
            and plan.get("signature") == _plan_signature(config)
        ):
            stored = plan.get("actions")
            if isinstance(stored, list):
                today_actions = _actions_with_results(stored, state)
            if isinstance(plan.get("observed_window"), dict):
                observed_window = plan["observed_window"]
        next_action = _next_action_at(today_actions, current)
        if next_action is None:
            next_action = _next_weekday_action(config, local_now.date(), current)
        weekly = observation.get("limits", {}).get("weekly") if observation else None
        status = "weekly_exhausted" if _limit_exhausted(weekly) else "scheduled"
        if not config.get("enabled") and status == "scheduled":
            status = "automation_disabled"

    busy_start, busy_end = window["busy_start_local"], window["busy_end_local"]
    confidence = (
        "observed" if observed_window else ("estimated" if observation is None else "planned")
    )
    return {
        "busy_period": {
            "start_local": busy_start,
            "end_local": busy_end,
            "timezone": config["timezone"],
            "active_weekdays": window["active_weekdays"],
            "strategy": window["strategy"],
        },
        "observed_window": observed_window,
        "usage_source": observation.get("source") if observation else None,
        "usage_captured_at": observation.get("captured_at") if observation else None,
        "today_actions": today_actions,
        "next_action_at": next_action,
        "status": status,
        "confidence": confidence,
    }


def tick_schedule(
    paths: AppPaths,
    config: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Synchronize usage and evaluate at most one idempotent anchor action."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    window = config["windows"]["five_hour"]
    with FileLock(
        paths.runtime_dir / "schedule.lock",
        timeout=0,
        error_code=ErrorCode.ALREADY_RUNNING,
    ):
        if (
            not config.get("enabled")
            or not window.get("enabled")
            or window.get("mode") != "adaptive"
        ):
            return {**schedule_snapshot(paths, config, now=current), "event": "no_action"}
        plan = _ensure_plan(paths, config, current)
        state = load_state(paths)
        actions = _actions_with_results(plan["actions"], state)
        grace = int(window["reset_grace_seconds"])
        due = [
            action
            for action in actions
            if _parse_iso(action["scheduled_at"]) <= current and action["status"] == "planned"
        ]
        if not due:
            return {**schedule_snapshot(paths, config, now=current), "event": "no_action"}
        action = due[-1]
        scheduled = _parse_iso(action["scheduled_at"])
        if (current - scheduled).total_seconds() > max(grace, 300):
            _record_action(paths, action["id"], "skipped_missed", "planned", current)
            return {**schedule_snapshot(paths, config, now=current), "event": "missed_not_replayed"}

        observation: dict[str, Any] | None = None
        measurement_error: AppError | None = None
        try:
            from .usage import query_usage

            observation = query_usage(paths, config)
        except AppError as exc:
            measurement_error = exc

        weekly = observation.get("limits", {}).get("weekly") if observation else None
        if _limit_exhausted(weekly):
            _record_action(paths, action["id"], "weekly_exhausted", "observed", current)
            return {
                **schedule_snapshot(paths, config, now=current),
                "status": "weekly_exhausted",
                "event": "weekly_exhausted",
            }
        five_hour = observation.get("limits", {}).get("five_hour") if observation else None
        if isinstance(five_hour, dict) and _active_window(five_hour, current, grace):
            _record_action(paths, action["id"], "manual_window_detected", "observed", current)
            _replan_from_observation(paths, config, current, five_hour)
            return {
                **schedule_snapshot(paths, config, now=current),
                "event": "manual_window_detected",
            }

        confidence = "observed" if observation else "estimated"
        try:
            from .claude import run_anchor

            anchor_result = run_anchor(paths, config)
        except AppError as exc:
            _record_action(
                paths, action["id"], "anchor_failed", confidence, current, exc.code.value
            )
            result = {**schedule_snapshot(paths, config, now=current), "event": "anchor_failed"}
            result["error"] = exc.to_dict()
            if measurement_error:
                result["measurement_error"] = measurement_error.to_dict()
            return result
        _record_action(paths, action["id"], "anchor_succeeded", confidence, current)
        result = {
            **schedule_snapshot(paths, config, now=current),
            "event": "anchor_succeeded",
            "anchor": anchor_result,
        }
        if measurement_error:
            result["measurement_error"] = measurement_error.to_dict()
        return result


def _ensure_plan(paths: AppPaths, config: dict[str, Any], now: datetime) -> dict[str, Any]:
    local_date = now.astimezone(ZoneInfo(config["timezone"])).date()
    signature = _plan_signature(config)
    state = load_state(paths)
    plan = state.get("adaptive_plan")
    if (
        isinstance(plan, dict)
        and plan.get("date") == local_date.isoformat()
        and plan.get("signature") == signature
    ):
        return plan
    plan = {
        "date": local_date.isoformat(),
        "signature": signature,
        "actions": ideal_actions_for_day(config, local_date),
        "observed_window": None,
        "generated_at": now.isoformat(),
    }
    update_state(paths, lambda value: value.__setitem__("adaptive_plan", plan))
    return plan


def _replan_from_observation(
    paths: AppPaths,
    config: dict[str, Any],
    now: datetime,
    observed: dict[str, Any],
) -> None:
    reset_value = observed.get("resets_at")
    if not isinstance(reset_value, str):
        return
    reset = _parse_iso(reset_value)
    zone = ZoneInfo(config["timezone"])
    local_now = now.astimezone(zone)
    window = config["windows"]["five_hour"]
    end_hour, end_minute = (int(part) for part in window["busy_end_local"].split(":"))
    busy_end = datetime.combine(
        local_now.date(), time(end_hour, end_minute), tzinfo=zone
    ).astimezone(timezone.utc)
    cursor = reset + timedelta(seconds=int(window["reset_grace_seconds"]))
    interval = timedelta(minutes=int(window["interval_minutes"]))
    state = load_state(paths)
    raw_plan = state.get("adaptive_plan")
    existing: dict[str, Any] = raw_plan if isinstance(raw_plan, dict) else {}
    past = [
        action
        for action in existing.get("actions", [])
        if isinstance(action, dict) and _parse_iso(str(action.get("scheduled_at"))) <= now
    ]
    actions = list(past)
    index = len(actions)
    while cursor <= busy_end:
        actions.append(
            {
                "id": f"{local_now.date().isoformat()}-observed-{index}-{cursor.isoformat()}",
                "scheduled_at": cursor.isoformat(),
                "kind": "anchor",
                "status": "planned",
                "confidence": "observed",
            }
        )
        cursor += interval
        index += 1
    plan = {
        "date": local_now.date().isoformat(),
        "signature": _plan_signature(config),
        "actions": actions,
        "observed_window": observed,
        "generated_at": now.isoformat(),
    }
    update_state(paths, lambda value: value.__setitem__("adaptive_plan", plan))


def _record_action(
    paths: AppPaths,
    action_id: str,
    status: str,
    confidence: str,
    now: datetime,
    error: str | None = None,
) -> None:
    def record(state: dict[str, Any]) -> None:
        state.setdefault("schedule_action_results", {})[action_id] = {
            "status": status,
            "confidence": confidence,
            "completed_at": now.isoformat(),
            "error": error,
        }

    update_state(paths, record)


def _actions_with_results(actions: list[Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    results = state.get("schedule_action_results", {})
    merged: list[dict[str, Any]] = []
    for raw in actions:
        if not isinstance(raw, dict):
            continue
        action = dict(raw)
        outcome = results.get(action.get("id")) if isinstance(results, dict) else None
        if isinstance(outcome, dict):
            action.update(outcome)
        merged.append(action)
    return merged


def _fresh_observation(value: Any, now: datetime) -> dict[str, Any] | None:
    if not isinstance(value, dict) or not isinstance(value.get("captured_at"), str):
        return None
    try:
        age = max(0, int((now - _parse_iso(value["captured_at"])).total_seconds()))
    except ValueError:
        return None
    result = dict(value)
    result["freshness_seconds"] = age
    result["fresh"] = age <= 900
    return result if result["fresh"] else None


def _active_window(value: Any, now: datetime, grace: int) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("resets_at"), str):
        return False
    try:
        reset = _parse_iso(value["resets_at"])
    except ValueError:
        return False
    return timedelta(seconds=grace) < reset - now <= timedelta(minutes=315)


def _limit_exhausted(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("used_percentage"), int | float)
        and float(value["used_percentage"]) >= 100
    )


def _next_action_at(actions: list[dict[str, Any]], now: datetime) -> str | None:
    candidates = [
        action["scheduled_at"]
        for action in actions
        if action.get("status") == "planned" and _parse_iso(action["scheduled_at"]) > now
    ]
    return min(candidates, key=_parse_iso) if candidates else None


def _next_weekday_action(config: dict[str, Any], start: date, now: datetime) -> str | None:
    for offset in range(1, 9):
        actions = ideal_actions_for_day(config, start + timedelta(days=offset))
        candidates = [
            action["scheduled_at"] for action in actions if _parse_iso(action["scheduled_at"]) > now
        ]
        if candidates:
            return candidates[0]
    return None


def _plan_signature(config: dict[str, Any]) -> str:
    window = config["windows"]["five_hour"]
    relevant = {
        "timezone": config["timezone"],
        "busy_start_local": window["busy_start_local"],
        "busy_end_local": window["busy_end_local"],
        "active_weekdays": window["active_weekdays"],
        "interval_minutes": window["interval_minutes"],
        "reset_grace_seconds": window["reset_grace_seconds"],
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:16]
