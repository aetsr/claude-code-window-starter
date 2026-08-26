from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import AppError, ErrorCode
from .io_utils import atomic_write_json, read_json
from .paths import AppPaths
from .windows import _parse_iso

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 4,
    "enabled": False,
    "background_enabled": False,
    "timezone": "Europe/Istanbul",
    "model": "auto",
    "prompt": "Respond with OK.",
    "timeout_seconds": 120,
    "log_retention_days": 30,
    "windows": {
        "five_hour": {
            "enabled": True,
            "mode": "adaptive",
            "busy_start_local": "08:00",
            "busy_end_local": "17:00",
            "active_weekdays": [1, 2, 3, 4, 5],
            "strategy": "maximize_quota",
            "reset_grace_seconds": 180,
            # Retained as the explicit manual-calibration fallback.
            "anchor_iso": None,
            "interval_minutes": 303,  # 5 hours 3 minutes
        },
        "weekly": {
            "enabled": False,
            "anchor_iso": None,
            "interval_minutes": 10080,  # 7 days
        },
    },
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


def _strip_unknown(supplied: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *supplied* with any keys not present in *expected* removed recursively."""
    result: dict[str, Any] = {}
    for key, expected_value in expected.items():
        if key not in supplied:
            continue
        value = supplied[key]
        if isinstance(value, dict) and isinstance(expected_value, dict):
            result[key] = _strip_unknown(value, expected_value)
        else:
            result[key] = value
    return result


def migrate_config(supplied: dict[str, Any]) -> dict[str, Any]:
    """Migrate config from v1 through v4 without enabling new automation."""
    raw_version = supplied.get("schema_version", 1)
    if isinstance(raw_version, int | str) and str(raw_version).isdigit():
        version: Any = int(raw_version)
    else:
        version = raw_version

    if version == 4:
        normalized = copy.deepcopy(supplied)
        normalized["schema_version"] = 4
        return normalized

    # Existing v3 installations keep their fixed anchor behavior. Users can
    # opt into adaptive mode explicitly from the app, CLI, or Telegram.
    if version == 3:
        migrated_v3 = copy.deepcopy(supplied)
        migrated_v3["schema_version"] = 4
        windows = migrated_v3.setdefault("windows", {})
        five_hour = windows.setdefault("five_hour", {})
        five_hour.update(
            {
                "mode": "manual",
                "busy_start_local": "08:00",
                "busy_end_local": "17:00",
                "active_weekdays": [1, 2, 3, 4, 5],
                "strategy": "maximize_quota",
                "reset_grace_seconds": 180,
            }
        )
        return migrated_v3

    # v2→v3: Remove old automation fields, add windows section
    if version == 2:
        migrated_v2 = copy.deepcopy(supplied)
        migrated_v2["schema_version"] = 4
        # Remove deprecated v2 fields
        migrated_v2.pop("schedule_time", None)
        migrated_v2.pop("automation_mode", None)
        migrated_v2.pop("reset_grace_seconds", None)
        migrated_v2.pop("allow_catch_up", None)
        migrated_v2.pop("prevent_duplicate_daily_run", None)
        # Ensure windows section exists (use defaults)
        if "windows" not in migrated_v2:
            migrated_v2["windows"] = {
                "five_hour": {
                    "enabled": True,
                    "mode": "manual",
                    "busy_start_local": "08:00",
                    "busy_end_local": "17:00",
                    "active_weekdays": [1, 2, 3, 4, 5],
                    "strategy": "maximize_quota",
                    "reset_grace_seconds": 180,
                    "anchor_iso": None,
                    "interval_minutes": 303,
                },
                "weekly": {
                    "enabled": False,
                    "anchor_iso": None,
                    "interval_minutes": 10080,
                },
            }
        return migrated_v2

    # v1→v2→v3
    if version != 1:
        raise AppError(ErrorCode.CONFIG_INVALID, "Unsupported config schema_version")

    migrated: dict[str, Any] = {
        key: copy.deepcopy(value)
        for key, value in supplied.items()
        if key
        in {
            "schema_version",
            "enabled",
            "timezone",
            "model",
            "prompt",
            "timeout_seconds",
            "log_retention_days",
            "telegram",
        }
    }
    migrated["schema_version"] = 4
    migrated["background_enabled"] = False
    migrated["windows"] = {
        "five_hour": {
            "enabled": True,
            "mode": "manual",
            "busy_start_local": "08:00",
            "busy_end_local": "17:00",
            "active_weekdays": [1, 2, 3, 4, 5],
            "strategy": "maximize_quota",
            "reset_grace_seconds": 180,
            "anchor_iso": None,
            "interval_minutes": 303,
        },
        "weekly": {
            "enabled": False,
            "anchor_iso": None,
            "interval_minutes": 10080,
        },
    }
    telegram = migrated.get("telegram")
    if isinstance(telegram, dict):
        telegram.pop("notify_updates", None)
    return migrated


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    _reject_unknown(config, DEFAULT_CONFIG)
    if config.get("schema_version") != 4:
        raise AppError(ErrorCode.CONFIG_INVALID, "Unsupported config schema_version")

    # Validate timezone
    try:
        ZoneInfo(str(config.get("timezone")))
    except (ZoneInfoNotFoundError, TypeError) as exc:
        raise AppError(ErrorCode.CONFIG_INVALID, "timezone must be an IANA timezone") from exc

    # Validate prompt
    prompt = config.get("prompt")
    telegram = config.get("telegram")
    if not isinstance(prompt, str) or not prompt.strip():
        raise AppError(ErrorCode.CONFIG_INVALID, "prompt must not be empty")
    if not isinstance(telegram, dict):
        raise AppError(ErrorCode.CONFIG_INVALID, "telegram must be an object")
    if len(prompt) > int(telegram.get("max_prompt_length", 500)):
        raise AppError(ErrorCode.CONFIG_INVALID, "prompt exceeds max_prompt_length")

    # Validate Telegram fields
    for field in ("allowed_user_ids", "allowed_chat_ids", "allowed_channel_ids"):
        values = telegram.get(field)
        if not isinstance(values, list) or any(type(item) is not int for item in values):
            raise AppError(ErrorCode.CONFIG_INVALID, f"{field} must contain numeric IDs")
    # Empty allowlists are valid — bot will reject all unauthorized messages.
    for field in ("notification_chat_id", "notification_channel_id"):
        value = telegram.get(field)
        if value is not None and type(value) is not int:
            raise AppError(ErrorCode.CONFIG_INVALID, f"{field} must be a numeric ID or null")

    # Validate boolean fields
    for field in ("enabled", "background_enabled"):
        if type(config.get(field)) is not bool:
            raise AppError(ErrorCode.CONFIG_INVALID, f"{field} must be boolean")

    # Validate Telegram boolean fields
    for field in (
        "enabled",
        "commands_in_private_chat_only",
        "notify_success",
        "notify_failure",
    ):
        if type(telegram.get(field)) is not bool:
            raise AppError(ErrorCode.CONFIG_INVALID, f"telegram.{field} must be boolean")

    # Validate numeric ranges
    for name, low, high in (
        ("timeout_seconds", 10, 1800),
        ("log_retention_days", 1, 3650),
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

    # Validate windows configuration
    windows = config.get("windows")
    if not isinstance(windows, dict):
        raise AppError(ErrorCode.CONFIG_INVALID, "windows must be an object")

    for wtype in ("five_hour", "weekly"):
        w = windows.get(wtype)
        if not isinstance(w, dict):
            raise AppError(ErrorCode.CONFIG_INVALID, f"windows.{wtype} must be an object")

        # enabled must be bool
        if type(w.get("enabled")) is not bool:
            raise AppError(ErrorCode.CONFIG_INVALID, f"windows.{wtype}.enabled must be boolean")

        # If enabled, must have anchor_iso and interval_minutes configured
        if w.get("enabled"):
            anchor = w.get("anchor_iso")
            interval = w.get("interval_minutes")

            # anchor_iso can be None (not yet configured) or a valid ISO datetime
            if anchor is not None:
                if not isinstance(anchor, str):
                    raise AppError(
                        ErrorCode.CONFIG_INVALID,
                        f"windows.{wtype}.anchor_iso must be an ISO datetime string or null",
                    )
                try:
                    _parse_iso(anchor)
                except ValueError as exc:
                    raise AppError(
                        ErrorCode.CONFIG_INVALID,
                        f"windows.{wtype}.anchor_iso must be a valid ISO datetime",
                    ) from exc

            # interval_minutes must be positive integer
            if type(interval) is not int or interval <= 0:
                raise AppError(
                    ErrorCode.CONFIG_INVALID,
                    f"windows.{wtype}.interval_minutes must be positive integer",
                )

    five_hour = windows["five_hour"]
    if five_hour.get("mode") not in {"adaptive", "manual"}:
        raise AppError(
            ErrorCode.CONFIG_INVALID, "windows.five_hour.mode must be adaptive or manual"
        )
    if five_hour.get("strategy") != "maximize_quota":
        raise AppError(
            ErrorCode.CONFIG_INVALID,
            "windows.five_hour.strategy must be maximize_quota",
        )
    for field in ("busy_start_local", "busy_end_local"):
        value = five_hour.get(field)
        if not isinstance(value, str) or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) is None:
            raise AppError(ErrorCode.CONFIG_INVALID, f"windows.five_hour.{field} must be HH:MM")
    start_minutes = _time_minutes(five_hour["busy_start_local"])
    end_minutes = _time_minutes(five_hour["busy_end_local"])
    if start_minutes >= end_minutes:
        raise AppError(
            ErrorCode.CONFIG_INVALID,
            "busy_start_local must be before busy_end_local; overnight periods are unsupported",
        )
    weekdays = five_hour.get("active_weekdays")
    if (
        not isinstance(weekdays, list)
        or not weekdays
        or any(type(day) is not int or day < 1 or day > 7 for day in weekdays)
        or len(set(weekdays)) != len(weekdays)
    ):
        raise AppError(
            ErrorCode.CONFIG_INVALID,
            "windows.five_hour.active_weekdays must contain unique ISO weekdays 1 through 7",
        )
    grace = five_hour.get("reset_grace_seconds")
    if type(grace) is not int or not 0 <= grace <= 3600:
        raise AppError(
            ErrorCode.CONFIG_INVALID,
            "windows.five_hour.reset_grace_seconds must be between 0 and 3600",
        )

    return config


def load_config(paths: AppPaths, *, create: bool = False) -> dict[str, Any]:
    exists = paths.config_file.exists()
    supplied = read_json(paths.config_file, {})
    if not isinstance(supplied, dict):
        raise AppError(ErrorCode.CONFIG_INVALID, "Config root must be an object")
    # A missing file is a genuinely new installation and receives adaptive
    # defaults. An existing v1-v3 document is migrated conservatively.
    migrated = migrate_config(supplied) if exists else {}
    # Strip unknown fields when loading from disk (they may come from an older app version).
    # save_config still validates strictly via validate_config → _reject_unknown.
    migrated = _strip_unknown(migrated, DEFAULT_CONFIG)
    config = validate_config(_merge(DEFAULT_CONFIG, migrated))
    if create and not exists:
        save_config(paths, config)
    elif exists and supplied.get("schema_version") != 4:
        save_config(paths, config)
    return config


def save_config(paths: AppPaths, config: dict[str, Any]) -> None:
    # Accept the v3-shaped dictionaries used by existing local integrations,
    # but persist only the complete v4 contract. A missing mode means the
    # caller intended the former fixed-anchor behavior.
    raw_version = config.get("schema_version", 4)
    if str(raw_version) not in {"3", "4"}:
        raise AppError(ErrorCode.CONFIG_INVALID, "Unsupported config schema_version")
    supplied = migrate_config(config) if str(raw_version) == "3" else config
    supplied_five_hour = supplied.get("windows", {}).get("five_hour", {})
    normalized = _merge(DEFAULT_CONFIG, supplied)
    if isinstance(supplied_five_hour, dict) and "mode" not in supplied_five_hour:
        normalized["windows"]["five_hour"]["mode"] = "manual"
    normalized["schema_version"] = 4
    validate_config(normalized)
    atomic_write_json(paths.config_file, normalized)


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


def _time_minutes(value: str) -> int:
    hours, minutes = value.split(":", 1)
    return int(hours) * 60 + int(minutes)
