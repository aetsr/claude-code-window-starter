from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import AppError, ErrorCode
from .io_utils import atomic_write_json, read_json
from .locks import FileLock
from .paths import AppPaths

DEFAULT_STATE: dict[str, Any] = {
    "schema_version": 2,
    "last_run": None,
    "last_automatic_date": None,
    "automatic_blocked_date": None,
    "model_cache": None,
    "pending_automatic": None,
    "next_automatic_retry_at": None,
    "telegram_offset": 0,
    "telegram_confirmations": {},
    "telegram_rate_limits": {},
    "notification_queue": [],
}


def load_state(paths: AppPaths) -> dict[str, Any]:
    state = read_json(paths.state_file, DEFAULT_STATE.copy())
    if not isinstance(state, dict):
        raise AppError(ErrorCode.STATE_WRITE_FAILED, "State file must contain an object")
    version = state.get("schema_version", 1)
    if version not in {1, 2}:
        raise AppError(ErrorCode.STATE_WRITE_FAILED, "Unsupported or invalid state file")
    result = {**DEFAULT_STATE, **state, "schema_version": 2}
    if version == 1:
        atomic_write_json(paths.state_file, result)
    return result


def save_state(paths: AppPaths, state: dict[str, Any]) -> None:
    state = {**DEFAULT_STATE, **state, "schema_version": 2}
    atomic_write_json(paths.state_file, state)


def update_state(paths: AppPaths, updater: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with FileLock(paths.runtime_dir / "state.lock", timeout=5, error_code=ErrorCode.STATE_WRITE_FAILED):
        state = load_state(paths)
        updater(state)
        save_state(paths, state)
        return state
