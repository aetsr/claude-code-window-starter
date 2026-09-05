from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from . import __version__
from .claude import run_anchor, run_claude
from .config import load_config, save_config, set_config_value
from .errors import AppError, ErrorCode
from .health import diagnose, health_report
from .logging_utils import log_event, rotate_logs, sanitize
from .paths import AppPaths
from .scheduler import next_runs, schedule_snapshot, tick_schedule
from .service_utils import send_mac_notification, service_action
from .state import load_state, update_state
from .telegram_api import TelegramAPI
from .telegram_bot import TelegramBot, notify
from .usage import query_usage
from .windows import _parse_iso, advance_window, format_countdown


def envelope(
    ok: bool, status: str, data: Any = None, error: AppError | None = None
) -> dict[str, Any]:
    return {
        "schema_version": 4,
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
    run_parser.add_argument(
        "--window-type", choices=["five_hour", "weekly"], help="Window being triggered"
    )
    sub.add_parser(
        "usage",
        help="Read Claude Code subscription usage (cache, OAuth, then CLI /usage fallback)",
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

    calibrate_parser = sub.add_parser("calibrate")
    calibrate_parser.add_argument("--window-type", choices=["five_hour", "weekly"], required=True)
    calibrate_parser.add_argument("--anchor", required=True, help="ISO datetime string (UTC)")

    schedule = sub.add_parser("schedule")
    schedule.add_argument("--apply-launchd", action="store_true")
    schedule.add_argument(
        "--tick", action="store_true", help="Evaluate one idempotent scheduler tick"
    )
    schedule.add_argument(
        "--network-state",
        choices=["online", "offline"],
        help=argparse.SUPPRESS,
    )
    sub.add_parser("anchor", help=argparse.SUPPRESS)

    bot = sub.add_parser("telegram-bot")
    bot.add_argument("--token-stdin", action="store_true")
    bot.add_argument("--supervisor-pid", type=int)
    telegram_test = sub.add_parser("telegram-test")
    telegram_test.add_argument("--no-message", action="store_true")
    telegram_test.add_argument("--token-stdin", action="store_true")
    telegram_pair = sub.add_parser("telegram-pair")
    telegram_pair.add_argument("--code", required=True)
    telegram_pair.add_argument("--token-stdin", action="store_true")
    telegram_user = sub.add_parser("telegram-user")
    telegram_user.add_argument("action", choices=["list", "add", "remove"])
    telegram_user.add_argument("--user-id", type=int, default=None)
    telegram_user.add_argument("--chat-id", type=int, default=None)

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
    now = datetime.now(timezone.utc)
    runs = next_runs(paths, config)

    # Build window status for each window type
    windows_status = {}
    for wtype in ("five_hour", "weekly"):
        w = config.get("windows", {}).get(wtype, {})
        next_run = runs.get(wtype)
        if wtype == "five_hour" and w.get("mode") == "adaptive":
            next_run = None
        countdown = format_countdown(next_run, now) if next_run else "—"
        windows_status[wtype] = {
            "enabled": w.get("enabled", False),
            "anchor_iso": w.get("anchor_iso"),
            "next_run_at": next_run.isoformat() if next_run else None,
            "countdown": countdown,
            "last_triggered_at": state.get(f"{wtype}_last_triggered_at"),
            "last_result": state.get(f"{wtype}_last_result"),
            "calibration_needed": state.get(f"{wtype}_calibration_needed"),
        }

    # Check whether the Telegram LaunchAgent is currently running
    telegram_running = False
    try:
        service_action("telegram", "status")
        telegram_running = True
    except AppError:
        telegram_running = False

    # Read the supervisor status file for accurate worker/token state.
    from .health import _telegram_supervisor_status

    tg_super = _telegram_supervisor_status(paths)
    telegram_worker_running = bool(
        telegram_running
        and tg_super.get("supervisor_alive", False)
        and tg_super.get("worker_running", False)
    )
    telegram_token_available = tg_super.get("token_available", None)

    adaptive = schedule_snapshot(paths, config, now=now)
    legacy_next = adaptive.get("next_action_at")
    return {
        "enabled": config["enabled"],
        "background_enabled": config["background_enabled"],
        "timezone": config["timezone"],
        "telegram_enabled": config["telegram"]["enabled"],
        "telegram_service_running": telegram_running,
        "telegram_worker_running": telegram_worker_running,
        "telegram_token_available": telegram_token_available,
        "windows": windows_status,
        "schedule": adaptive,
        "next_run_at": legacy_next,
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
        trigger = args.trigger or "macos_ui"
        window_type = args.window_type
        started = datetime.now(timezone.utc).isoformat()
        try:
            result = run_claude(
                paths, config, trigger=trigger, window_type=window_type, dry_run=bool(args.dry_run)
            )
            if (
                not args.dry_run
                and window_type  # only notify on scheduled window runs, not manual UI triggers
                and config["telegram"]["enabled"]
                and config["telegram"]["notify_success"]
            ):
                window_label = "5 saatlik" if window_type == "five_hour" else "Haftalık"
                notify(
                    paths,
                    f"✅ {window_label} pencere tamamlandı.\nModel: {result['selected_model']}",
                )
            rotate_logs(paths, config["log_retention_days"])

            # Update window state on success
            if window_type and not args.dry_run:

                def update_window(state: dict[str, Any]) -> None:
                    now = datetime.now(timezone.utc)
                    next_at = advance_window(window_type, config, now)
                    state[f"{window_type}_last_triggered_at"] = now.isoformat()
                    state[f"{window_type}_next_run_at"] = next_at.isoformat()
                    state[f"{window_type}_last_result"] = {
                        "status": "success",
                        "trigger_time": now.isoformat(),
                        "selected_model": result["selected_model"],
                        "response_summary": result["response"],
                    }
                    state[f"{window_type}_calibration_needed"] = None

                update_state(paths, update_window)

            return "dry_run" if args.dry_run else "success", result
        except AppError as exc:
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
    if command == "usage":
        return "success", query_usage(paths, load_config(paths, create=True))
    if command == "anchor":
        return "success", run_anchor(paths, load_config(paths, create=True))
    if command == "calibrate":
        config = load_config(paths, create=True)
        window_type = args.window_type
        anchor_iso = args.anchor

        # Validate anchor is valid ISO datetime (accept both Z and +00:00 UTC suffixes)
        try:
            _parse_iso(anchor_iso)
        except ValueError as exc:
            raise AppError(ErrorCode.CONFIG_INVALID, f"Invalid ISO datetime: {anchor_iso}") from exc

        # Update config
        if window_type == "five_hour":
            config["windows"]["five_hour"]["mode"] = "manual"
        config["windows"][window_type]["anchor_iso"] = anchor_iso
        save_config(paths, config)

        # Compute next run and update state
        def update_calibration(state: dict[str, Any]) -> None:
            now = datetime.now(timezone.utc)
            next_at = advance_window(window_type, config, now)
            state[f"{window_type}_next_run_at"] = next_at.isoformat()
            state[f"{window_type}_calibration_needed"] = None

        update_state(paths, update_calibration)

        next_window = next_runs(paths, config).get(window_type)
        next_iso = next_window.isoformat() if next_window else "unknown"
        config_for_tz = load_config(paths, create=True)
        tz_name = config_for_tz.get("timezone", "UTC")
        from .telegram_bot import _fmt_dt as _tg_fmt

        window_label = "5 saatlik" if window_type == "five_hour" else "Haftalık"
        next_display = _tg_fmt(next_window, tz_name) if next_window else "hesaplanamadı"
        notify(paths, f"⚙️ {window_label} pencere kalibre edildi.\nSonraki çalışma: {next_display}")
        return "success", {
            "window_type": window_type,
            "anchor_iso": anchor_iso,
            "next_run_at": next_iso,
        }
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
            return "success", config
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        updated = set_config_value(paths, args.key, value)
        return "success", updated
    if command == "schedule":
        config = load_config(paths, create=True)
        if args.tick:
            result = tick_schedule(paths, config)
            _notify_schedule_event(paths, config, result)
            return str(result.get("event", "success")), result
        if args.network_state == "offline":

            def _mark_offline(state: dict[str, Any]) -> None:
                state["network_went_offline_at"] = datetime.now(timezone.utc).isoformat()

            update_state(paths, _mark_offline)
            return "connectivity_recorded", {"online": False}
        if args.network_state == "online":
            state = load_state(paths)
            offline_at_str = state.get("network_went_offline_at")
            missed: list[str] = []
            now = datetime.now(timezone.utc)
            if offline_at_str:
                try:
                    offline_at = _parse_iso(offline_at_str)
                    for wtype in ("five_hour", "weekly"):
                        w = config.get("windows", {}).get(wtype, {})
                        if not w.get("enabled") or not w.get("anchor_iso"):
                            continue
                        next_run_str = state.get(f"{wtype}_next_run_at")
                        if next_run_str:
                            try:
                                next_run_dt = _parse_iso(next_run_str)
                                if offline_at <= next_run_dt <= now:
                                    missed.append(wtype)
                            except ValueError:
                                pass
                except (ValueError, KeyError):
                    pass

            def _clear_offline(state: dict[str, Any]) -> None:
                state.pop("network_went_offline_at", None)
                for wtype in missed:
                    state[f"{wtype}_calibration_needed"] = True

            update_state(paths, _clear_offline)
            if missed:
                window_names = {"five_hour": "5 saatlik", "weekly": "haftalık"}
                missed_str = ", ".join(window_names.get(w, w) for w in missed)
                msg = (
                    "🔌 İnternet bağlantısı yeniden kuruldu.\n\n"
                    f"Çevrimdışıyken kaçırılan pencereler: *{missed_str}*\n\n"
                    "Lütfen Mac uygulamasından veya bot üzerinden kalibre edin."
                )
                try:
                    notify(paths, msg)
                except AppError as exc:
                    log_event(
                        paths,
                        {
                            "status": "connectivity_notification_failed",
                            "error_code": exc.code.value,
                        },
                    )
                send_mac_notification("Claude Window Starter", msg)
            return "connectivity_recorded", {"online": True, "missed_windows": missed}
        result = schedule_snapshot(paths, config)
        next_window_runs = next_runs(paths, config)
        result["next_runs"] = {k: v.isoformat() if v else None for k, v in next_window_runs.items()}
        result["launchd_plist"] = None
        return "success", result
    if command == "telegram-bot":
        token = _read_token_stdin() if args.token_stdin else ""
        TelegramBot(paths, token=token, supervisor_pid=args.supervisor_pid).run_forever()
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
        uids = config["telegram"].setdefault("allowed_user_ids", [])
        if user_id not in uids:
            uids.append(user_id)
        cids = config["telegram"].setdefault("allowed_chat_ids", [])
        if chat_id not in cids:
            cids.append(chat_id)
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
            service_action("telegram", "restart")
        except AppError:
            service_restarted = False
        return "success", {
            "user_id": user_id,
            "chat_id": chat_id,
            "enabled": True,
            "message_sent": True,
            "service_restarted": service_restarted,
        }
    if command == "telegram-user":
        config = load_config(paths, create=True)
        action = args.action
        if action == "list":
            return "success", {
                "allowed_user_ids": config["telegram"].get("allowed_user_ids", []),
                "allowed_chat_ids": config["telegram"].get("allowed_chat_ids", []),
            }
        if action == "add":
            if args.user_id is not None:
                ids = config["telegram"].setdefault("allowed_user_ids", [])
                if args.user_id not in ids:
                    ids.append(args.user_id)
            if args.chat_id is not None:
                ids = config["telegram"].setdefault("allowed_chat_ids", [])
                if args.chat_id not in ids:
                    ids.append(args.chat_id)
            save_config(paths, config)
            return "success", {
                "allowed_user_ids": config["telegram"]["allowed_user_ids"],
                "allowed_chat_ids": config["telegram"]["allowed_chat_ids"],
            }
        if action == "remove":
            if args.user_id is not None:
                config["telegram"]["allowed_user_ids"] = [
                    uid
                    for uid in config["telegram"].get("allowed_user_ids", [])
                    if uid != args.user_id
                ]
            if args.chat_id is not None:
                config["telegram"]["allowed_chat_ids"] = [
                    cid
                    for cid in config["telegram"].get("allowed_chat_ids", [])
                    if cid != args.chat_id
                ]
            save_config(paths, config)
            return "success", {
                "allowed_user_ids": config["telegram"]["allowed_user_ids"],
                "allowed_chat_ids": config["telegram"]["allowed_chat_ids"],
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
        return "success", service_action(args.target, args.action)
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
    except Exception as exc:
        result = envelope(False, "error", error=AppError(ErrorCode.CONFIG_INVALID, str(exc)))
        print(
            json.dumps(result, ensure_ascii=False, indent=2) if json_output else str(exc),
            file=sys.stderr,
        )
        return 1


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


def _notify_schedule_event(paths: AppPaths, config: dict[str, Any], result: dict[str, Any]) -> None:
    event = str(result.get("event", ""))
    messages = {
        "anchor_succeeded": "✅ Adaptif 5 saatlik kota penceresi Haiku ile başlatıldı.",
        "manual_window_detected": (
            "ℹ️ Manuel Claude kullanımıyla açılmış aktif pencere algılandı; "
            "plan gerçek resete göre güncellendi."
        ),
        "weekly_exhausted": "⛔ Haftalık kota dolu; otomatik anchor işlemleri durduruldu.",
        "anchor_failed": (
            "⚠️ Adaptif anchor kalıcı olarak başarısız oldu; bu eylem yeniden denenmeyecek."
        ),
    }
    message = messages.get(event)
    telegram = config.get("telegram", {})
    if not message or not telegram.get("enabled"):
        return
    actions = result.get("today_actions", [])
    completed = [
        action
        for action in actions
        if isinstance(action, dict) and action.get("status") != "planned"
    ]
    action_id = completed[-1].get("id") if completed else result.get("next_action_at")
    dedup_key = f"{event}:{action_id}"
    state = load_state(paths)
    if dedup_key in state.get("notification_dedup", {}):
        return
    try:
        notify(paths, message)
    except AppError:
        return

    def mark(current: dict[str, Any]) -> None:
        current.setdefault("notification_dedup", {})[dedup_key] = datetime.now(
            timezone.utc
        ).isoformat()

    update_state(paths, mark)


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
