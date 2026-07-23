from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .claude import run_claude
from .config import DEFAULT_CONFIG, load_config, save_config, set_config_value
from .deployment import ReleaseManager
from .errors import AppError, ErrorCode
from .health import diagnose, health_report
from .io_utils import atomic_write_bytes, atomic_write_text
from .logging_utils import log_event, rotate_logs, sanitize
from .paths import AppPaths
from .scheduler import catch_up_due, next_run
from .state import load_state
from .telegram_api import TelegramAPI, telegram_token
from .telegram_bot import TelegramBot, notify


def envelope(ok: bool, status: str, data: Any = None, error: AppError | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
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
    diagnose_parser = sub.add_parser("diagnose")
    diagnose_parser.add_argument("--server", action="store_true")
    health_parser = sub.add_parser("health")
    health_parser.add_argument("--no-services", action="store_true")
    health_parser.add_argument("--json", action="store_true")

    run_parser = sub.add_parser("run")
    mode = run_parser.add_mutually_exclusive_group()
    mode.add_argument("--manual", action="store_true")
    mode.add_argument("--automatic", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--trigger", choices=["server_cli", "macos_ui", "telegram", "automatic", "catch_up"])

    config_parser = sub.add_parser("config")
    config_sub = config_parser.add_subparsers(dest="config_action", required=True)
    config_sub.add_parser("init")
    config_sub.add_parser("get")
    config_sub.add_parser("patch-stdin")
    set_parser = config_sub.add_parser("set")
    set_parser.add_argument("key")
    set_parser.add_argument("value", help="JSON value")

    schedule = sub.add_parser("schedule")
    schedule.add_argument("--apply-systemd", action="store_true")
    schedule.add_argument("--apply-launchd", action="store_true")

    sub.add_parser("telegram-bot")
    sub.add_parser("telegram-test")

    update = sub.add_parser("update")
    action = update.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--apply", action="store_true")
    action.add_argument("--scheduled", action="store_true")

    releases = sub.add_parser("releases")
    releases.add_argument("--limit", type=int, default=20)
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--release")
    rollback.add_argument("--yes", action="store_true")
    logs = sub.add_parser("logs")
    logs.add_argument("--lines", type=int, default=20)
    service = sub.add_parser("service")
    service.add_argument("target", choices=["telegram", "timer", "update-timer"])
    service.add_argument("action", choices=["start", "stop", "restart", "status"])
    sub.add_parser("version")
    return parser


def _status(paths: AppPaths) -> dict[str, Any]:
    config = load_config(paths, create=True)
    state = load_state(paths)
    return {
        "enabled": config["enabled"],
        "execution_mode": config["execution_mode"],
        "schedule_time": config["schedule_time"],
        "timezone": config["timezone"],
        "next_run": next_run(config).isoformat(),
        "last_run": state.get("last_run"),
        "last_deployment": state.get("last_deployment"),
        "health": health_report(paths),
        "active_release": ReleaseManager(paths).active_manifest(),
    }


def _server_facts() -> dict[str, Any]:
    import shutil
    import subprocess

    commands = {
        "uname": ["uname", "-m"],
        "lscpu": ["lscpu"],
        "memory": ["free", "-h"],
        "os_release": ["cat", "/etc/os-release"],
        "disk": ["df", "-h"],
    }
    result: dict[str, Any] = {}
    for name, argv in commands.items():
        if not shutil.which(argv[0]):
            result[name] = {"available": False}
            continue
        process = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
            shell=False,
        )
        result[name] = {
            "available": True,
            "exit_code": process.returncode,
            "output": process.stdout[:12000],
        }
    return result


def _write_systemd_schedule(paths: AppPaths, config: dict[str, Any]) -> Path:
    configured = os.environ.get("CLAUDE_STARTER_SYSTEMD_USER_DIR")
    root = Path(configured) if configured else Path.home() / ".config/systemd/user"
    unit_dir = root / "claude-window-starter-run.timer.d"
    path = unit_dir / "schedule.conf"
    hour, minute = config["schedule_time"].split(":")
    content = (
        "[Timer]\n"
        "OnCalendar=\n"
        f"OnCalendar=*-*-* {hour}:{minute}:00 {config['timezone']}\n"
        "Persistent=true\n"
    )
    atomic_write_text(path, content)
    return path


def execute(args: argparse.Namespace, paths: AppPaths) -> tuple[str, Any]:
    paths.ensure()
    command = args.command
    if command == "status":
        return "success", _status(paths)
    if command == "diagnose":
        data = diagnose(paths)
        if args.server:
            data["server_facts"] = _server_facts()
        return "success", data
    if command == "health":
        data = health_report(paths, include_services=not args.no_services)
        if not data["ok"]:
            raise AppError(ErrorCode.HEALTH_CHECK_FAILED)
        return "healthy", data
    if command == "run":
        config = load_config(paths, create=True)
        if args.dry_run:
            trigger = args.trigger or "server_cli"
            dry = True
        elif args.automatic:
            trigger = args.trigger or ("catch_up" if catch_up_due(paths, config) else "automatic")
            dry = False
        else:
            trigger = args.trigger or ("macos_ui" if config["execution_mode"] == "this_mac" else "server_cli")
            dry = False
        started = datetime.now(timezone.utc).isoformat()
        try:
            result = run_claude(paths, config, trigger=trigger, dry_run=dry)
            if not dry and config["telegram"]["enabled"] and config["telegram"]["notify_success"]:
                notify(paths, f"Claude request succeeded.\nModel: {result['selected_model']}\n{result['usage_window_verification']['message']}")
            rotate_logs(paths, config["log_retention_days"])
            return "dry_run" if dry else "success", result
        except AppError as exc:
            log_event(paths, {"start_time": started, "end_time": datetime.now(timezone.utc).isoformat(), "trigger_source": trigger, "status": "failed", "error_code": exc.code.value, "sanitized_error": exc.message})
            if config["telegram"]["enabled"] and config["telegram"]["notify_failure"]:
                try:
                    notify(paths, f"Claude request failed: {exc.code.value} — {exc.message}")
                except AppError:
                    pass
            raise
    if command == "config":
        if args.config_action == "init":
            config = load_config(paths, create=True)
        elif args.config_action == "get":
            config = load_config(paths, create=True)
        elif args.config_action == "patch-stdin":
            try:
                patch = json.load(sys.stdin)
            except json.JSONDecodeError as exc:
                raise AppError(ErrorCode.CONFIG_INVALID, "stdin must contain a JSON object") from exc
            if not isinstance(patch, dict):
                raise AppError(ErrorCode.CONFIG_INVALID, "stdin must contain a JSON object")
            config = load_config(paths, create=True)
            allowed = {
                "enabled", "schedule_time", "timezone", "model", "prompt", "timeout_seconds",
                "allow_catch_up", "prevent_duplicate_daily_run", "telegram", "deployment",
            }
            unknown = set(patch) - allowed
            if unknown:
                raise AppError(ErrorCode.CONFIG_INVALID, f"Unsupported config fields: {sorted(unknown)}")
            config = _deep_patch(config, patch)
            save_config(paths, config)
        else:
            try:
                value = json.loads(args.value)
            except json.JSONDecodeError:
                value = args.value
            config = set_config_value(paths, args.key, value)
        return "success", config
    if command == "schedule":
        config = load_config(paths, create=True)
        path = _write_systemd_schedule(paths, config) if args.apply_systemd else None
        launchd = _write_launchd_schedule(config) if args.apply_launchd else None
        return "success", {
            "next_run": next_run(config).isoformat(),
            "drop_in": str(path) if path else None,
            "launchd_plist": str(launchd) if launchd else None,
        }
    if command == "telegram-bot":
        TelegramBot(paths).run_forever()
        return "stopped", None
    if command == "telegram-test":
        api = TelegramAPI(telegram_token(paths))
        identity = api.get_me()
        config = load_config(paths, create=True)["telegram"]
        target = config.get("notification_channel_id") or config.get("notification_chat_id")
        if type(target) is int:
            api.send_message(target, "Claude Window Starter Telegram test succeeded.")
        return "success", {"bot_id": identity.get("id"), "username": identity.get("username"), "message_sent": type(target) is int}
    if command == "update":
        manager = ReleaseManager(paths)
        if args.apply:
            config = load_config(paths, create=True)
            if config["telegram"]["enabled"] and config["telegram"]["notify_updates"]:
                notify(paths, "Deployment started for the configured protected branch.")
            try:
                deployed = manager.apply()
            except AppError as exc:
                if config["telegram"]["enabled"] and config["telegram"]["notify_updates"]:
                    try:
                        notify(paths, f"Deployment failed: {exc.code.value} — {exc.message}")
                    except AppError:
                        pass
                raise
            if config["telegram"]["enabled"] and config["telegram"]["notify_updates"]:
                notify(paths, f"Deployment succeeded: {deployed['commit_sha'][:12]}")
            return "success", deployed
        if args.scheduled:
            config = load_config(paths, create=True)
            deployment = config["deployment"]
            if not deployment["auto_update_enabled"]:
                return "disabled", {"update_check_performed": False}
            result = manager.check()
            if result["update_available"] and config["telegram"]["enabled"] and config["telegram"]["notify_updates"]:
                notify(paths, f"Git update available: {result['short_commit_sha']} on {result['branch']}")
            if result["update_available"] and deployment["auto_apply_updates"]:
                return "success", manager.apply()
            return "success", result
        return "success", manager.check()
    if command == "releases":
        return "success", ReleaseManager(paths).list_releases()[: max(1, min(args.limit, 100))]
    if command == "rollback":
        if not args.yes:
            raise AppError(ErrorCode.CONFIG_INVALID, "Rollback requires --yes after explicit confirmation")
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
    if "--json" in raw:
        raw = [item for item in raw if item != "--json"]
        raw.insert(0, "--json")
    args = parser.parse_args(raw)
    paths = AppPaths.discover(args.home)
    json_output = bool(args.json or getattr(args, "json", False))
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
    if result["ok"]:
        return json.dumps(result["data"], ensure_ascii=False, indent=2, default=str)
    return f"{result['error']['code']}: {result['error']['message']}"


def _deep_patch(target: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(target)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_patch(result[key], value)
        else:
            result[key] = value
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
    if code.value.startswith(("GIT_", "UPDATE_", "DEPLOYMENT_", "RELEASE_", "HEALTH_", "SYMLINK_", "SERVICE_", "PRE_DEPLOY", "DEPENDENCY_", "UNTRUSTED_")):
        return 7
    return 4


def _service_action(target: str, action: str) -> dict[str, Any]:
    import shutil
    import subprocess

    systemctl = shutil.which("systemctl")
    if not systemctl:
        raise AppError(ErrorCode.SYSTEMD_FAILED, "systemctl is unavailable")
    units = {
        "telegram": "claude-window-starter-telegram.service",
        "timer": "claude-window-starter-run.timer",
        "update-timer": "claude-window-starter-update-check.timer",
    }
    unit = units[target]
    verb = "show" if action == "status" else action
    argv = [systemctl, "--user", verb, unit]
    if action == "status":
        argv.extend(["--property=ActiveState,SubState"])
    process = subprocess.run(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
        check=False,
        shell=False,
    )
    if process.returncode != 0:
        raise AppError(ErrorCode.SYSTEMD_FAILED, f"Service {action} failed")
    return {"unit": unit, "action": action, "output": process.stdout.strip()}


def _write_launchd_schedule(config: dict[str, Any]) -> Path:
    import subprocess

    override = os.environ.get("CLAUDE_STARTER_LAUNCHD_PLIST")
    path = Path(override) if override else Path.home() / "Library/LaunchAgents/com.openai.claude-window-starter.plist"
    if not path.is_file():
        raise AppError(ErrorCode.LAUNCHD_FAILED, "LaunchAgent is not installed")
    try:
        document = plistlib.loads(path.read_bytes())
        hour, minute = (int(part) for part in config["schedule_time"].split(":"))
        document["StartCalendarInterval"] = {"Hour": hour, "Minute": minute}
        atomic_write_bytes(path, plistlib.dumps(document, fmt=plistlib.FMT_XML))
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        raise AppError(ErrorCode.LAUNCHD_FAILED, "Unable to update LaunchAgent schedule") from exc
    if os.environ.get("CLAUDE_STARTER_SKIP_SERVICE_RESTART") == "1":
        return path
    domain = f"gui/{os.getuid()}"
    label = "com.openai.claude-window-starter"
    subprocess.run(
        ["/bin/launchctl", "bootout", f"{domain}/{label}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        shell=False,
    )
    process = subprocess.run(
        ["/bin/launchctl", "bootstrap", domain, str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
        shell=False,
    )
    if process.returncode != 0:
        raise AppError(ErrorCode.LAUNCHD_FAILED, "LaunchAgent reload failed")
    return path
