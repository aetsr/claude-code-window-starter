from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .claude import run_claude
from .config import load_config, save_config, set_config_value
from .errors import AppError, ErrorCode
from .health import diagnose, health_report
from .io_utils import atomic_write_bytes
from .logging_utils import log_event, rotate_logs, sanitize
from .paths import AppPaths
from .scheduler import automatic_due, clear_pending, mark_pending, next_automatic_run
from .state import load_state, update_state
from .telegram_api import TelegramAPI
from .telegram_bot import TelegramBot, notify


def envelope(
    ok: bool, status: str, data: Any = None, error: AppError | None = None
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "ok": ok,
        "status": status,
        "error": error.to_dict() if error else None,
        "sanitized_message": error.message if error else None,
        "data": sanitize(data),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-window-starter")
    parser.add_argument("--home", help="Application data directory")
    parser.add_argument("--json", action="store_true", help="Emit a JSON envelope")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("diagnose")
    health_parser = sub.add_parser("health")
    health_parser.add_argument("--no-services", action="store_true")
    run_parser = sub.add_parser("run")
    mode = run_parser.add_mutually_exclusive_group()
    mode.add_argument("--manual", action="store_true")
    mode.add_argument("--automatic", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    run_parser.add_argument(
        "--trigger", choices=["macos_ui", "telegram", "automatic", "catch_up", "background"]
    )

    config_parser = sub.add_parser("config")
    config_sub = config_parser.add_subparsers(dest="config_action", required=True)
    config_sub.add_parser("init")
    config_sub.add_parser("get")
    config_sub.add_parser("validate")
    config_sub.add_parser("patch-stdin")
    set_parser = config_sub.add_parser("set")
    set_parser.add_argument("key")
    set_parser.add_argument("value", help="JSON value")

    schedule = sub.add_parser("schedule")
    schedule.add_argument("--apply-launchd", action="store_true")
    schedule.add_argument(
        "--network-state",
        choices=["online", "offline"],
        help=argparse.SUPPRESS,
    )

    bot = sub.add_parser("telegram-bot")
    bot.add_argument("--token-stdin", action="store_true")
    telegram_test = sub.add_parser("telegram-test")
    telegram_test.add_argument("--no-message", action="store_true")
    telegram_test.add_argument("--token-stdin", action="store_true")
    telegram_pair = sub.add_parser("telegram-pair")
    telegram_pair.add_argument("--code", required=True)
    telegram_pair.add_argument("--token-stdin", action="store_true")

    releases = sub.add_parser("releases")
    releases.add_argument("--limit", type=int, default=20)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--release")
    rollback.add_argument("--yes", action="store_true")
    logs = sub.add_parser("logs")
    logs.add_argument("--lines", type=int, default=20)
    service = sub.add_parser("service")
    service.add_argument("target", choices=["background", "telegram"])
    service.add_argument("action", choices=["start", "stop", "restart", "status"])
    sub.add_parser("version")
    return parser


def _status(paths: AppPaths) -> dict[str, Any]:
    config = load_config(paths, create=True)
    state = load_state(paths)
    return {
        "enabled": config["enabled"],
        "background_enabled": config["background_enabled"],
        "telegram_enabled": config["telegram"]["enabled"],
        "automation_mode": config["automation_mode"],
        "schedule_time": config["schedule_time"],
        "timezone": config["timezone"],
        "next_run": next_automatic_run(paths, config).isoformat(),
        "automatic_due": automatic_due(paths, config),
        "pending_automatic": state.get("pending_automatic"),
        "automatic_blocked": state.get("automatic_blocked"),
        "last_run": state.get("last_run"),
        "usage_window": state.get("usage_window"),
        "health": health_report(paths),
    }


def _read_token_stdin() -> str:
    token = sys.stdin.read(8193).strip()
    if not token or len(token) > 8192 or "\x00" in token or "\n" in token or "\r" in token:
        raise AppError(ErrorCode.TELEGRAM_TOKEN_MISSING, "A valid Keychain token was not provided")
    return token


def execute(args: argparse.Namespace, paths: AppPaths) -> tuple[str, Any]:
    paths.ensure()
    command = args.command
    if command == "status":
        return "success", _status(paths)
    if command == "diagnose":
        return "success", diagnose(paths)
    if command == "health":
        data = health_report(paths, include_services=not args.no_services)
        if not data["ok"]:
            raise AppError(ErrorCode.HEALTH_CHECK_FAILED)
        return "healthy", data
    if command == "run":
        config = load_config(paths, create=True)
        is_automatic = bool(
            args.automatic or args.trigger in {"automatic", "catch_up", "background"}
        )
        if is_automatic and not config["enabled"]:
            return "disabled", {"real_request_sent": False, "reason": "automation_disabled"}
        if is_automatic and not args.dry_run and not automatic_due(paths, config):
            return "not_due", {"real_request_sent": False, "reason": "usage_window_not_due"}
        trigger = args.trigger or ("background" if is_automatic else "macos_ui")
        started = datetime.now(timezone.utc).isoformat()
        try:
            result = run_claude(paths, config, trigger=trigger, dry_run=bool(args.dry_run))
            if is_automatic and not args.dry_run:
                clear_pending(paths)
            if (
                not args.dry_run
                and config["telegram"]["enabled"]
                and config["telegram"]["notify_success"]
            ):
                # Build notification with usage information if available
                message_parts = [
                    f"Claude request succeeded. Model: {result['selected_model']}",
                    result['usage_window_verification']['message'],
                ]
                # Add usage percentage and reset time if available
                rate_limits = result.get("rate_limits")
                if isinstance(rate_limits, dict):
                    five_hour = rate_limits.get("five_hour", {})
                    used_pct = five_hour.get("used_percentage")
                    resets_at = five_hour.get("resets_at")
                    if used_pct is not None:
                        message_parts.append(f"Usage: {int(used_pct)}%")
                    if resets_at is not None:
                        from datetime import datetime as dt
                        reset_time = dt.fromtimestamp(resets_at, tz=timezone.utc)
                        message_parts.append(f"Resets: {reset_time.strftime('%H:%M %Z')}")
                notify(paths, "\n".join(message_parts))
            rotate_logs(paths, config["log_retention_days"])
            return "dry_run" if args.dry_run else "success", result
        except AppError as exc:
            if is_automatic and exc.code in {
                ErrorCode.NETWORK_UNAVAILABLE,
                ErrorCode.DNS_FAILURE,
                ErrorCode.ALREADY_RUNNING,
            }:
                mark_pending(paths, config, exc.code.value)
                return (
                    "pending_connectivity" if exc.code != ErrorCode.ALREADY_RUNNING else "pending",
                    {
                        "real_request_sent": False,
                        "reason": exc.code.value,
                        "pending": True,
                    },
                )
            if exc.code == ErrorCode.RATE_OR_USAGE_LIMIT:
                # Update next_window_run_at for UI even on manual trigger.
                from .usage import next_window_time

                next_at, _ = next_window_time(None, completed_at=datetime.now(timezone.utc), grace_seconds=int(config.get("reset_grace_seconds", 60)))
                update_state(paths, lambda state: state.__setitem__("next_window_run_at", next_at.isoformat()))
                if is_automatic:
                    mark_pending(
                        paths,
                        config,
                        exc.code.value,
                        minimum_delay=900,
                        maximum_delay=3600,
                    )
                # Notify about rate limit with reset time
                if (
                    not args.dry_run
                    and config["telegram"]["enabled"]
                    and config["telegram"]["notify_failure"]
                ):
                    try:
                        reset_msg = f"Claude usage limit reached. Resumes at {next_at.strftime('%H:%M %Z')}"
                        notify(paths, f"Claude request failed: {exc.code.value} — {reset_msg}")
                    except AppError:
                        pass
                if is_automatic:
                    return "pending_limit", {
                        "real_request_sent": False,
                        "reason": exc.code.value,
                        "pending": True,
                    }
            if is_automatic and exc.code in {
                ErrorCode.ALREADY_RAN_TODAY,
                ErrorCode.WINDOW_NOT_DUE,
            }:
                return "skipped", {"real_request_sent": False, "reason": exc.code.value}
            if is_automatic:
                error_code = exc.code.value

                def block_automatic(state: dict[str, Any]) -> None:
                    state["automatic_blocked"] = {
                        "error_code": error_code,
                        "blocked_at": datetime.now(timezone.utc).isoformat(),
                    }
                    state["pending_automatic"] = None
                    state["next_automatic_retry_at"] = None

                update_state(paths, block_automatic)
            log_event(
                paths,
                {
                    "start_time": started,
                    "end_time": datetime.now(timezone.utc).isoformat(),
                    "trigger_source": trigger,
                    "status": "failed",
                    "error_code": exc.code.value,
                    "sanitized_error": exc.message,
                },
            )
            if config["telegram"]["enabled"] and config["telegram"]["notify_failure"]:
                try:
                    notify(paths, f"Claude request failed: {exc.code.value} — {exc.message}")
                except AppError:
                    pass
            raise
    if command == "config":
        if args.config_action in {"init", "get"}:
            return "success", load_config(paths, create=True)
        if args.config_action == "validate":
            return "success", load_config(paths)
        if args.config_action == "patch-stdin":
            try:
                patch = json.load(sys.stdin)
            except json.JSONDecodeError as exc:
                raise AppError(
                    ErrorCode.CONFIG_INVALID, "stdin must contain a JSON object"
                ) from exc
            if not isinstance(patch, dict):
                raise AppError(ErrorCode.CONFIG_INVALID, "stdin must contain a JSON object")
            config = load_config(paths, create=True)
            config = _deep_patch(config, patch)
            save_config(paths, config)
            update_state(paths, lambda state: state.__setitem__("automatic_blocked", None))
            return "success", config
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        updated = set_config_value(paths, args.key, value)
        update_state(paths, lambda state: state.__setitem__("automatic_blocked", None))
        return "success", updated
    if command == "schedule":
        config = load_config(paths, create=True)
        if args.network_state == "offline":
            if config["enabled"] and automatic_due(paths, config):
                mark_pending(paths, config, ErrorCode.NETWORK_UNAVAILABLE.value)
            return "connectivity_recorded", {"online": False}
        if args.network_state == "online":
            state = load_state(paths)
            pending = state.get("pending_automatic")
            if isinstance(pending, dict) and pending.get("reason") in {
                ErrorCode.NETWORK_UNAVAILABLE.value,
                ErrorCode.DNS_FAILURE.value,
            }:
                update_state(
                    paths,
                    lambda current: current.__setitem__(
                        "next_automatic_retry_at",
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            return "connectivity_recorded", {"online": True}
        path = _write_launchd_schedule(config) if args.apply_launchd else None
        return "success", {
            "next_run": next_automatic_run(paths, config).isoformat(),
            "launchd_plist": str(path) if path else None,
        }
    if command == "telegram-bot":
        token = _read_token_stdin() if args.token_stdin else ""
        TelegramBot(paths, token=token).run_forever()
        return "stopped", None
    if command == "telegram-test":
        token = _read_token_stdin() if args.token_stdin else ""
        api = TelegramAPI(token)
        identity = api.get_me()
        config = load_config(paths, create=True)["telegram"]
        target = config.get("notification_channel_id") or config.get("notification_chat_id")
        if type(target) is int and not args.no_message:
            api.send_message(target, "Claude Window Starter Telegram test succeeded.")
        return "success", {
            "bot_id": identity.get("id"),
            "username": identity.get("username"),
            "message_sent": type(target) is int and not args.no_message,
        }
    if command == "telegram-pair":
        if not args.token_stdin:
            raise AppError(ErrorCode.TELEGRAM_TOKEN_MISSING)
        code = str(args.code).strip().upper()
        if not code.isalnum() or not 6 <= len(code) <= 16:
            raise AppError(ErrorCode.TELEGRAM_PAIRING_FAILED, "Pairing code is invalid")
        api = TelegramAPI(_read_token_stdin(), timeout=15)
        updates = api.get_updates(0, timeout=0)
        user_id, chat_id, next_offset = _find_pairing(updates, code)
        api.send_message(chat_id, "Claude Window Starter eşleştirmesi tamamlandı.")
        config = load_config(paths, create=True)
        config["telegram"]["allowed_user_ids"] = [user_id]
        config["telegram"]["allowed_chat_ids"] = [chat_id]
        config["telegram"]["notification_chat_id"] = chat_id
        config["telegram"]["notification_channel_id"] = None
        config["telegram"]["enabled"] = True
        save_config(paths, config)
        update_state(
            paths,
            lambda state: state.__setitem__("telegram_offset", next_offset),
        )
        service_restarted = True
        try:
            _service_action("telegram", "restart")
        except AppError:
            service_restarted = False
        return "success", {
            "user_id": user_id,
            "chat_id": chat_id,
            "enabled": True,
            "message_sent": True,
            "service_restarted": service_restarted,
        }
    if command == "releases":
        from .releases import ReleaseManager

        return "success", ReleaseManager(paths).list_releases()[: max(1, min(args.limit, 100))]
    if command == "rollback":
        if not args.yes:
            raise AppError(
                ErrorCode.CONFIG_INVALID, "Rollback requires --yes after explicit confirmation"
            )
        from .releases import ReleaseManager

        return "success", ReleaseManager(paths).rollback(args.release)
    if command == "logs":
        from .logging_utils import tail_sanitized

        return "success", {"lines": tail_sanitized(paths.log_file, args.lines)}
    if command == "service":
        return "success", _service_action(args.target, args.action)
    if command == "version":
        return "success", {"application_version": __version__, "python": platform.python_version()}
    raise AppError(ErrorCode.CONFIG_INVALID, "Unknown command")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    raw = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(raw)
    paths = AppPaths.discover(args.home)
    json_output = bool(args.json)
    try:
        status, data = execute(args, paths)
        result = envelope(True, status, data)
        print(
            json.dumps(result, ensure_ascii=False, indent=2, default=str)
            if json_output
            else _human(result)
        )
        return 0
    except AppError as exc:
        result = envelope(False, "error", error=exc)
        print(
            json.dumps(result, ensure_ascii=False, indent=2)
            if json_output
            else f"{exc.code.value}: {exc.message}",
            file=sys.stderr,
        )
        return _exit_code(exc.code)
    except KeyboardInterrupt:
        return 130


def _human(result: dict[str, Any]) -> str:
    return (
        json.dumps(result["data"], ensure_ascii=False, indent=2, default=str)
        if result["ok"]
        else f"{result['error']['code']}: {result['error']['message']}"
    )


def _deep_patch(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(target)
    for key, value in patch.items():
        result[key] = (
            _deep_patch(result[key], value)
            if isinstance(value, dict) and isinstance(result.get(key), dict)
            else value
        )
    return result


def _find_pairing(updates: list[dict[str, Any]], code: str) -> tuple[int, int, int]:
    matches: list[tuple[int, int, int]] = []
    for update in updates:
        message = update.get("message")
        if not isinstance(message, dict):
            continue
        sender, chat, message_text = (
            message.get("from"),
            message.get("chat"),
            message.get("text"),
        )
        if (
            not isinstance(sender, dict)
            or not isinstance(chat, dict)
            or not isinstance(message_text, str)
        ):
            continue
        user_id, chat_id, update_id = (
            sender.get("id"),
            chat.get("id"),
            update.get("update_id"),
        )
        if type(user_id) is not int or type(chat_id) is not int or type(update_id) is not int:
            continue
        parts = message_text.strip().split()
        command_name = parts[0].split("@", 1)[0].lower() if parts else ""
        if (
            chat.get("type") == "private"
            and command_name == "/pair"
            and len(parts) == 2
            and parts[1].upper() == code
        ):
            matches.append((user_id, chat_id, update_id))
    unique = {(user_id, chat_id) for user_id, chat_id, _ in matches}
    if len(unique) != 1:
        raise AppError(
            ErrorCode.TELEGRAM_PAIRING_FAILED,
            "Send the displayed /pair code to the bot in one private chat, then retry",
        )
    user_id, chat_id = next(iter(unique))
    next_offset = max(item[2] for item in matches) + 1
    return user_id, chat_id, next_offset


def _exit_code(code: ErrorCode) -> int:
    if code in {ErrorCode.CONFIG_INVALID, ErrorCode.UNSUPPORTED_ARCH, ErrorCode.UNSUPPORTED_OS}:
        return 2
    if code in {
        ErrorCode.API_KEY_DETECTED,
        ErrorCode.CLAUDE_NOT_AUTHENTICATED,
        ErrorCode.CLAUDE_SESSION_EXPIRED,
    }:
        return 3
    if code.value.startswith("TELEGRAM_"):
        return 6
    if code in {
        ErrorCode.ROLLBACK_FAILED,
        ErrorCode.NO_HEALTHY_PREVIOUS_RELEASE,
        ErrorCode.INVALID_RELEASE,
    }:
        return 8
    if code in {
        ErrorCode.HEALTH_CHECK_FAILED,
        ErrorCode.LAUNCHD_FAILED,
        ErrorCode.RELEASE_PREPARATION_FAILED,
        ErrorCode.SYMLINK_SWITCH_FAILED,
    }:
        return 7
    return 4


def _service_action(target: str, action: str) -> dict[str, Any]:
    launchctl = "/bin/launchctl"
    if not Path(launchctl).exists():
        raise AppError(ErrorCode.LAUNCHD_FAILED, "launchctl is unavailable")
    label = f"com.openai.claude-window-starter.{target}"
    domain = f"gui/{os.getuid()}"
    if action == "status":
        argv = [launchctl, "print", f"{domain}/{label}"]
    elif action == "stop":
        argv = [launchctl, "kill", "SIGTERM", f"{domain}/{label}"]
    else:
        argv = [launchctl, "kickstart", "-k" if action == "restart" else "", f"{domain}/{label}"]
        argv = [item for item in argv if item]
    process = subprocess.run(
        argv, capture_output=True, text=True, timeout=20, check=False, shell=False
    )
    if process.returncode != 0:
        raise AppError(ErrorCode.LAUNCHD_FAILED, f"Unable to {action} {target} service")
    return {"label": label, "action": action, "output": process.stdout.strip()}


def _write_launchd_schedule(config: dict[str, Any]) -> Path:
    override = os.environ.get("CLAUDE_STARTER_LAUNCHD_PLIST")
    path = (
        Path(override)
        if override
        else Path.home() / "Library/LaunchAgents/com.openai.claude-window-starter.background.plist"
    )
    try:
        document = plistlib.loads(path.read_bytes())
        hour, minute = (int(part) for part in config["schedule_time"].split(":"))
        document["StartCalendarInterval"] = {"Hour": hour, "Minute": minute}
        atomic_write_bytes(path, plistlib.dumps(document, fmt=plistlib.FMT_XML))
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        raise AppError(ErrorCode.LAUNCHD_FAILED, "Unable to update LaunchAgent schedule") from exc
    return path
