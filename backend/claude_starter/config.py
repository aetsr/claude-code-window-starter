from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import AppError, ErrorCode
from .io_utils import atomic_write_json, read_json
from .paths import AppPaths

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 2,
    "enabled": False,
    "background_enabled": False,
    "automation_mode": "five_hour_window",
    "reset_grace_seconds": 60,
    "schedule_time": "08:00",
    "timezone": "Europe/Istanbul",
    "model": "auto",
    "prompt": "Respond with OK.",
    "timeout_seconds": 120,
    "allow_catch_up": True,
    "prevent_duplicate_daily_run": True,
    "log_retention_days": 30,
    "telegram": {
        "enabled": False,
        "allowed_user_ids": [],
        "allowed_chat_ids": [],
        "allowed_channel_ids": [],
        "notification_chat_id": None,
        "notification_channel_id": None,
        "commands_in_private_chat_only": True,
        "notify_success": True,
        "notify_failure": True,
        "command_cooldown_seconds": 3,
        "confirmation_ttl_seconds": 60,
        "max_prompt_length": 500,
    },
}


def _merge(default: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(default)
    for key, value in supplied.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def _reject_unknown(supplied: dict[str, Any], expected: dict[str, Any], prefix: str = "") -> None:
    unknown = set(supplied) - set(expected)
    if unknown:
        field = f"{prefix}." if prefix else ""
        raise AppError(
            ErrorCode.CONFIG_INVALID,
            f"Unsupported config fields under {field or 'root'}: {sorted(unknown)}",
        )
    for key, value in supplied.items():
        expected_value = expected[key]
        if isinstance(value, dict) and isinstance(expected_value, dict):
            _reject_unknown(value, expected_value, f"{prefix}.{key}".strip("."))


def migrate_config(supplied: dict[str, Any]) -> dict[str, Any]:
    """Convert the shipped v1 config without copying removed fields."""
    raw_version = supplied.get("schema_version", 1)
    if isinstance(raw_version, int | str) and str(raw_version).isdigit():
        version: Any = int(raw_version)
    else:
        version = raw_version
    if version == 2:
        normalized = copy.deepcopy(supplied)
        normalized["schema_version"] = 2
        return normalized
    if version != 1:
        raise AppError(ErrorCode.CONFIG_INVALID, "Unsupported config schema_version")

    migrated: dict[str, Any] = {
        key: copy.deepcopy(value)
        for key, value in supplied.items()
        if key
        in {
            "schema_version",
            "enabled",
            "schedule_time",
            "timezone",
            "model",
            "prompt",
            "timeout_seconds",
            "allow_catch_up",
            "prevent_duplicate_daily_run",
            "log_retention_days",
            "telegram",
        }
    }
    migrated["schema_version"] = 2
    migrated["background_enabled"] = False
    telegram = migrated.get("telegram")
    if isinstance(telegram, dict):
        telegram.pop("notify_updates", None)
    return migrated


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(config, DEFAULT_CONFIG)
    if config.get("schema_version") != 2:
        raise AppError(ErrorCode.CONFIG_INVALID, "Unsupported config schema_version")
    schedule = str(config.get("schedule_time", ""))
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", schedule):
        raise AppError(ErrorCode.CONFIG_INVALID, "schedule_time must use HH:MM")
    try:
        ZoneInfo(str(config.get("timezone")))
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise AppError(ErrorCode.CONFIG_INVALID, "timezone must be an IANA timezone") from exc
    prompt = config.get("prompt")
    telegram = config.get("telegram")
    if not isinstance(prompt, str) or not prompt.strip():
        raise AppError(ErrorCode.CONFIG_INVALID, "prompt must not be empty")
    if not isinstance(telegram, dict):
        raise AppError(ErrorCode.CONFIG_INVALID, "telegram must be an object")
    if len(prompt) > int(telegram.get("max_prompt_length", 500)):
        raise AppError(ErrorCode.CONFIG_INVALID, "prompt exceeds max_prompt_length")
    for field in ("allowed_user_ids", "allowed_chat_ids", "allowed_channel_ids"):
        values = telegram.get(field)
        if not isinstance(values, list) or any(type(item) is not int for item in values):
            raise AppError(ErrorCode.CONFIG_INVALID, f"{field} must contain numeric IDs")
    if telegram.get("enabled") and (
        not telegram.get("allowed_user_ids") or not telegram.get("allowed_chat_ids")
    ):
        raise AppError(
            ErrorCode.CONFIG_INVALID, "Telegram requires user and private-chat allowlists"
        )
    for field in ("notification_chat_id", "notification_channel_id"):
        value = telegram.get(field)
        if value is not None and type(value) is not int:
            raise AppError(ErrorCode.CONFIG_INVALID, f"{field} must be a numeric ID or null")
    for field in (
        "enabled",
        "background_enabled",
        "allow_catch_up",
        "prevent_duplicate_daily_run",
    ):
        if type(config.get(field)) is not bool:
            raise AppError(ErrorCode.CONFIG_INVALID, f"{field} must be boolean")
    if config.get("automation_mode") not in {"five_hour_window", "daily"}:
        raise AppError(ErrorCode.CONFIG_INVALID, "automation_mode is invalid")
    for field in (
        "enabled",
        "commands_in_private_chat_only",
        "notify_success",
        "notify_failure",
    ):
        if type(telegram.get(field)) is not bool:
            raise AppError(ErrorCode.CONFIG_INVALID, f"telegram.{field} must be boolean")
    for name, low, high in (
        ("timeout_seconds", 10, 1800),
        ("log_retention_days", 1, 3650),
        ("reset_grace_seconds", 0, 900),
    ):
        value = config.get(name)
        if type(value) is not int or not low <= value <= high:
            raise AppError(ErrorCode.CONFIG_INVALID, f"{name} must be between {low} and {high}")
    for name, low, high in (
        ("command_cooldown_seconds", 1, 3600),
        ("confirmation_ttl_seconds", 10, 3600),
        ("max_prompt_length", 1, 5000),
    ):
        value = telegram.get(name)
        if type(value) is not int or not low <= value <= high:
            raise AppError(
                ErrorCode.CONFIG_INVALID,
                f"telegram.{name} must be between {low} and {high}",
            )
    return config


def load_config(paths: AppPaths, *, create: bool = False) -> dict[str, Any]:
    supplied = read_json(paths.config_file, {})
    if not isinstance(supplied, dict):
        raise AppError(ErrorCode.CONFIG_INVALID, "Config root must be an object")
    migrated = migrate_config(supplied)
    _reject_unknown(migrated, DEFAULT_CONFIG)
    config = validate_config(_merge(DEFAULT_CONFIG, migrated))
    if create and not paths.config_file.exists():
        save_config(paths, config)
    elif paths.config_file.exists() and supplied.get("schema_version") != 2:
        save_config(paths, config)
    return config


def save_config(paths: AppPaths, config: dict[str, Any]) -> None:
    validate_config(config)
    atomic_write_json(paths.config_file, config)


def set_config_value(paths: AppPaths, dotted_key: str, value: Any) -> dict[str, Any]:
    config = load_config(paths, create=True)
    keys = dotted_key.split(".")
    cursor: dict[str, Any] = config
    for key in keys[:-1]:
        item = cursor.get(key)
        if not isinstance(item, dict):
            raise AppError(ErrorCode.CONFIG_INVALID, f"Unknown config key: {dotted_key}")
        cursor = item
    if keys[-1] not in cursor:
        raise AppError(ErrorCode.CONFIG_INVALID, f"Unknown config key: {dotted_key}")
    cursor[keys[-1]] = value
    save_config(paths, config)
    return config


def local_now(config: dict[str, Any]) -> datetime:
    return datetime.now(ZoneInfo(config["timezone"]))
