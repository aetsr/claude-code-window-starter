from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .errors import AppError, ErrorCode
from .io_utils import atomic_write_json, read_json
from .locks import FileLock
from .paths import AppPaths

DEFAULT_STATE: dict[str, Any] = {
    "schema_version": 1,
    "last_run": None,
    "last_automatic_date": None,
    "model_cache": None,
    "telegram_offset": 0,
    "telegram_confirmations": {},
    "telegram_rate_limits": {},
    "last_deployment": None,
}


def load_state(paths: AppPaths) -> dict[str, Any]:
    state = read_json(paths.state_file, DEFAULT_STATE.copy())
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise AppError(ErrorCode.STATE_WRITE_FAILED, "Unsupported or invalid state file")
    return {**DEFAULT_STATE, **state}


def save_state(paths: AppPaths, state: dict[str, Any]) -> None:
    atomic_write_json(paths.state_file, state)


def update_state(paths: AppPaths, updater: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    lock = paths.runtime_dir / "state.lock"
    with FileLock(lock, timeout=5, error_code=ErrorCode.STATE_WRITE_FAILED):
        state = load_state(paths)
        updater(state)
        save_state(paths, state)
        return state
