from __future__ import annotations

import copy
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
    "automatic_blocked": None,
    "automatic_blocked_date": None,
    "model_cache": None,
    "pending_automatic": None,
    "next_automatic_retry_at": None,
    "usage_window": None,
    "next_window_run_at": None,
    "telegram_offset": 0,
    "telegram_confirmations": {},
    "telegram_rate_limits": {},
    "notification_queue": [],
}


def load_state(paths: AppPaths) -> dict[str, Any]:
    raw = read_json(paths.state_file, None)
    # When the file is absent, treat it as an empty dict so we start from defaults.
    state: dict[str, Any] = raw if isinstance(raw, dict) else {}
    if raw is not None and not isinstance(raw, dict):
        raise AppError(ErrorCode.STATE_WRITE_FAILED, "State file must contain an object")
    raw_version = state.get("schema_version", 1)
    if isinstance(raw_version, int | str) and str(raw_version).isdigit():
        version: Any = int(raw_version)
    else:
        version = raw_version
    if state and version not in {1, 2}:
        raise AppError(ErrorCode.STATE_WRITE_FAILED, "Unsupported or invalid state file")
    # Deep-copy DEFAULT_STATE so that mutable nested values (e.g. telegram_rate_limits)
    # are never shared between callers, preventing cross-call or cross-test mutation.
    result: dict[str, Any] = copy.deepcopy(DEFAULT_STATE)
    result.update(state)
    result["schema_version"] = 2
    if version == 1:
        atomic_write_json(paths.state_file, result)
    return result


def save_state(paths: AppPaths, state: dict[str, Any]) -> None:
    state = {**DEFAULT_STATE, **state, "schema_version": 2}
    atomic_write_json(paths.state_file, state)


def update_state(paths: AppPaths, updater: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with FileLock(
        paths.runtime_dir / "state.lock", timeout=5, error_code=ErrorCode.STATE_WRITE_FAILED
    ):
        state = load_state(paths)
        updater(state)
        save_state(paths, state)
        return state
