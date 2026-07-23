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
from .config import load_config, local_now, save_config, set_config_value
from .errors import AppError, ErrorCode
from .health import diagnose, health_report
from .io_utils import atomic_write_bytes
from .logging_utils import log_event, rotate_logs, sanitize
from .paths import AppPaths
from .scheduler import automatic_due, clear_pending, mark_pending, next_run
from .state import load_state
from .telegram_api import TelegramAPI
from .telegram_bot import TelegramBot, notify


def envelope(ok: bool, status: str, data: Any = None, error: AppError | None = None) -> dict[str, Any]:
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

    bot = sub.add_parser("telegram-bot")
    bot.add_argument("--token-stdin", action="store_true")
    telegram_test = sub.add_parser("telegram-test")
    telegram_test.add_argument("--no-message", action="store_true")
    telegram_test.add_argument("--token-stdin", action="store_true")

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
        "schedule_time": config["schedule_time"],
        "timezone": config["timezone"],
        "next_run": next_run(config).isoformat(),
        "automatic_due": automatic_due(paths, config),
        "pending_automatic": state.get("pending_automatic"),
        "last_run": state.get("last_run"),
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
        is_automatic = bool(args.automatic or args.trigger in {"automatic", "catch_up", "background"})
        if is_automatic and not config["enabled"]:
            return "disabled", {"real_request_sent": False, "reason": "automation_disabled"}
        if is_automatic and not args.dry_run and not automatic_due(paths, config):
            return "not_due", {"real_request_sent": False, "reason": "scheduled_time_not_reached"}
        trigger = args.trigger or ("background" if is_automatic else "macos_ui")
        started = datetime.now(timezone.utc).isoformat()
        try:
            result = run_claude(paths, config, trigger=trigger, dry_run=bool(args.dry_run))
            if is_automatic and not args.dry_run:
                clear_pending(paths)
            if not args.dry_run and config["telegram"]["enabled"] and config["telegram"]["notify_success"]:
                notify(
                    paths,
                    f"Claude request succeeded. Model: {result['selected_model']}\n"
                    f"{result['usage_window_verification']['message']}",
                )
            rotate_logs(paths, config["log_retention_days"])
            return "dry_run" if args.dry_run else "success", result
        except AppError as exc:
            if is_automatic and exc.code in {
                ErrorCode.NETWORK_UNAVAILABLE,
                ErrorCode.DNS_FAILURE,
                ErrorCode.ALREADY_RUNNING,
            }:
                mark_pending(paths, config, exc.code.value)
                return "pending_connectivity" if exc.code != ErrorCode.ALREADY_RUNNING else "pending", {
                    "real_request_sent": False,
                    "reason": exc.code.value,
                    "pending": True,
                }
            if is_automatic:
                current_date = local_now(config).date().isoformat()
                from .state import update_state

                def block_automatic(state: dict[str, Any]) -> None:
                    state["automatic_blocked_date"] = current_date
                    state["pending_automatic"] = None
                    state["next_automatic_retry_at"] = None

                update_state(paths, block_automatic)
            if is_automatic and exc.code == ErrorCode.ALREADY_RAN_TODAY:
                return "skipped", {"real_request_sent": False, "reason": exc.code.value}
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
                raise AppError(ErrorCode.CONFIG_INVALID, "stdin must contain a JSON object") from exc
            if not isinstance(patch, dict):
                raise AppError(ErrorCode.CONFIG_INVALID, "stdin must contain a JSON object")
            allowed = {
                "enabled", "background_enabled", "schedule_time", "timezone", "model",
                "prompt", "timeout_seconds", "allow_catch_up", "prevent_duplicate_daily_run",
                "telegram",
            }
            unknown = set(patch) - allowed
            if unknown:
                raise AppError(ErrorCode.CONFIG_INVALID, f"Unsupported config fields: {sorted(unknown)}")
            config = load_config(paths, create=True)
            config = _deep_patch(config, patch)
            save_config(paths, config)
            return "success", config
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        return "success", set_config_value(paths, args.key, value)
    if command == "schedule":
        config = load_config(paths, create=True)
        path = _write_launchd_schedule(config) if args.apply_launchd else None
        return "success", {"next_run": next_run(config).isoformat(), "launchd_plist": str(path) if path else None}
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
        return "success", {"bot_id": identity.get("id"), "username": identity.get("username"), "message_sent": type(target) is int and not args.no_message}
    if command == "releases":
        from .releases import ReleaseManager

        return "success", ReleaseManager(paths).list_releases()[: max(1, min(args.limit, 100))]
    if command == "rollback":
        if not args.yes:
            raise AppError(ErrorCode.CONFIG_INVALID, "Rollback requires --yes after explicit confirmation")
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
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str) if json_output else _human(result))
        return 0
    except AppError as exc:
        result = envelope(False, "error", error=exc)
        print(json.dumps(result, ensure_ascii=False, indent=2) if json_output else f"{exc.code.value}: {exc.message}", file=sys.stderr)
        return _exit_code(exc.code)
    except KeyboardInterrupt:
        return 130


def _human(result: dict[str, Any]) -> str:
    return json.dumps(result["data"], ensure_ascii=False, indent=2, default=str) if result["ok"] else f"{result['error']['code']}: {result['error']['message']}"


def _deep_patch(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(target)
    for key, value in patch.items():
        result[key] = _deep_patch(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def _exit_code(code: ErrorCode) -> int:
    if code in {ErrorCode.CONFIG_INVALID, ErrorCode.UNSUPPORTED_ARCH, ErrorCode.UNSUPPORTED_OS}:
        return 2
    if code in {ErrorCode.API_KEY_DETECTED, ErrorCode.CLAUDE_NOT_AUTHENTICATED, ErrorCode.CLAUDE_SESSION_EXPIRED}:
        return 3
    if code.value.startswith("TELEGRAM_"):
        return 6
    if code in {ErrorCode.ROLLBACK_FAILED, ErrorCode.NO_HEALTHY_PREVIOUS_RELEASE, ErrorCode.INVALID_RELEASE}:
        return 8
    if code in {ErrorCode.HEALTH_CHECK_FAILED, ErrorCode.LAUNCHD_FAILED, ErrorCode.RELEASE_PREPARATION_FAILED, ErrorCode.SYMLINK_SWITCH_FAILED}:
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
    process = subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False, shell=False)
    if process.returncode != 0:
        raise AppError(ErrorCode.LAUNCHD_FAILED, f"Unable to {action} {target} service")
    return {"label": label, "action": action, "output": process.stdout.strip()}


def _write_launchd_schedule(config: dict[str, Any]) -> Path:
    override = os.environ.get("CLAUDE_STARTER_LAUNCHD_PLIST")
    path = Path(override) if override else Path.home() / "Library/LaunchAgents/com.openai.claude-window-starter.background.plist"
    try:
        document = plistlib.loads(path.read_bytes())
        hour, minute = (int(part) for part in config["schedule_time"].split(":"))
        document["StartCalendarInterval"] = {"Hour": hour, "Minute": minute}
        atomic_write_bytes(path, plistlib.dumps(document, fmt=plistlib.FMT_XML))
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        raise AppError(ErrorCode.LAUNCHD_FAILED, "Unable to update LaunchAgent schedule") from exc
    return path
