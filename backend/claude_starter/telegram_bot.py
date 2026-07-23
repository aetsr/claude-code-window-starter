from __future__ import annotations

import json
import secrets
import subprocess
import time
from datetime import datetime
from typing import Any

from .claude import WINDOW_UNVERIFIED
from .config import load_config, save_config
from .errors import AppError, ErrorCode
from .health import diagnose, health_report
from .locks import FileLock
from .logging_utils import log_event, tail_sanitized
from .paths import AppPaths
from .scheduler import next_run
from .state import load_state, update_state
from .telegram_api import TelegramAPI

HELP = """Claude Window Starter
/status /run /dryrun /diagnose /health
/schedule /settime HH:MM /timezone /settimezone IANA
/enable /disable /background on|off /next /last /logs
/model /setmodel auto|haiku|sonnet|opus /prompt /setprompt TEXT
/timer /restarttimer /version"""


class TelegramBot:
    def __init__(self, paths: AppPaths, api: TelegramAPI | None = None, token: str = "") -> None:
        self.paths = paths
        self.config = load_config(paths, create=True)
        self.telegram = self.config["telegram"]
        self.api = api or TelegramAPI(token)

    def authorized(self, user_id: int, chat_id: int, chat_type: str) -> bool:
        if user_id not in self.telegram["allowed_user_ids"]:
            return False
        if self.telegram["commands_in_private_chat_only"] and chat_type != "private":
            return False
        if chat_type == "private":
            allowed_chats = self.telegram["allowed_chat_ids"]
            return not allowed_chats or chat_id in allowed_chats
        return chat_id in self.telegram["allowed_chat_ids"]

    def _rate_allowed(self, user_id: int) -> bool:
        now = time.time()
        cooldown = int(self.telegram["command_cooldown_seconds"])
        state = load_state(self.paths)
        previous = float(state.get("telegram_rate_limits", {}).get(str(user_id), 0))
        if now - previous < cooldown:
            return False
        update_state(
            self.paths,
            lambda current: current.setdefault("telegram_rate_limits", {}).__setitem__(str(user_id), now),
        )
        return True

    def _confirmation(self, user_id: int, chat_id: int, action: str, value: str = "") -> dict[str, Any]:
        nonce = secrets.token_urlsafe(12)
        expiry = time.time() + int(self.telegram["confirmation_ttl_seconds"])

        def store(state: dict[str, Any]) -> None:
            state.setdefault("telegram_confirmations", {})[nonce] = {
                "user_id": user_id,
                "chat_id": chat_id,
                "action": action,
                "value": value,
                "expires": expiry,
            }

        update_state(self.paths, store)
        return {"inline_keyboard": [[
            {"text": "Confirm", "callback_data": f"confirm:{nonce}"},
            {"text": "Cancel", "callback_data": f"cancel:{nonce}"},
        ]]}

    def handle_update(self, update: dict[str, Any]) -> None:
        if isinstance(update.get("callback_query"), dict):
            self._handle_callback(update["callback_query"])
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return
        sender, chat, text = message.get("from"), message.get("chat"), message.get("text")
        if not isinstance(sender, dict) or not isinstance(chat, dict) or not isinstance(text, str):
            return
        user_id, chat_id, chat_type = int(sender.get("id", 0)), int(chat.get("id", 0)), str(chat.get("type", ""))
        if not self.authorized(user_id, chat_id, chat_type):
            log_event(self.paths, {"status": "unauthorized", "error_code": ErrorCode.TELEGRAM_UNAUTHORIZED.value})
            self.api.send_message(chat_id, "Unauthorized")
            return
        if not self._rate_allowed(user_id):
            self.api.send_message(chat_id, "Rate limited; try again shortly.")
            return
        command, _, argument = text.strip().partition(" ")
        command = command.split("@", 1)[0].lower()
        try:
            response, markup = self._command(command, argument.strip(), user_id, chat_id)
            self.api.send_message(chat_id, response, reply_markup=markup)
        except AppError as exc:
            self.api.send_message(chat_id, f"{exc.code.value}: {exc.message}")
        except Exception:
            self.api.send_message(chat_id, "INTERNAL_ERROR: Operation failed safely.")

    def _command(self, command: str, argument: str, user_id: int, chat_id: int) -> tuple[str, dict[str, Any] | None]:
        self.config = load_config(self.paths, create=True)
        self.telegram = self.config["telegram"]
        state = load_state(self.paths)
        if command in {"/start", "/help"}:
            return HELP, None
        if command == "/status":
            return _pretty({
                "enabled": self.config["enabled"],
                "background_enabled": self.config["background_enabled"],
                "schedule": f"{self.config['schedule_time']} {self.config['timezone']}",
                "next": next_run(self.config).isoformat(),
                "pending_automatic": state.get("pending_automatic"),
                "last_run": state.get("last_run"),
                "health": health_report(self.paths),
                "window_note": WINDOW_UNVERIFIED,
            }), None
        if command == "/run":
            return "Run a real Claude subscription request?", self._confirmation(user_id, chat_id, "run")
        if command == "/dryrun":
            _start_local_job("dry")
            return "Dry-run started; no Claude request will be sent.", None
        if command == "/diagnose":
            return _pretty(diagnose(self.paths)), None
        if command == "/health":
            return _pretty(health_report(self.paths)), None
        if command == "/schedule":
            return f"{self.config['schedule_time']} {self.config['timezone']}", None
        if command == "/settime":
            _validate_time(argument)
            self.config["schedule_time"] = argument
            save_config(self.paths, self.config)
            return f"Schedule updated. Next: {next_run(self.config).isoformat()}", None
        if command == "/timezone":
            return str(self.config["timezone"]), None
        if command == "/settimezone":
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(argument)
            except ZoneInfoNotFoundError as exc:
                raise AppError(ErrorCode.CONFIG_INVALID, "Invalid IANA timezone") from exc
            self.config["timezone"] = argument
            save_config(self.paths, self.config)
            return f"Timezone updated. Next: {next_run(self.config).isoformat()}", None
        if command in {"/enable", "/disable"}:
            self.config["enabled"] = command == "/enable"
            save_config(self.paths, self.config)
            return f"Automation {'enabled' if self.config['enabled'] else 'disabled'}.", None
        if command == "/background":
            if argument not in {"on", "off"}:
                raise AppError(ErrorCode.CONFIG_INVALID, "Use /background on or /background off")
            self.config["background_enabled"] = argument == "on"
            save_config(self.paths, self.config)
            return f"Background mode {'enabled' if self.config['background_enabled'] else 'disabled'}.", None
        if command == "/next":
            return next_run(self.config).isoformat(), None
        if command == "/last":
            return _pretty(state.get("last_run")), None
        if command == "/logs":
            return "\n".join(tail_sanitized(self.paths.log_file, 15)) or "No logs.", None
        if command == "/model":
            return str(self.config["model"]), None
        if command == "/setmodel":
            if argument not in {"auto", "haiku", "sonnet", "opus"}:
                raise AppError(ErrorCode.CONFIG_INVALID, "Model must be auto, haiku, sonnet, or opus")
            self.config["model"] = argument
            save_config(self.paths, self.config)
            return f"Model set to {argument}.", None
        if command == "/prompt":
            return str(self.config["prompt"]), None
        if command == "/setprompt":
            if not argument or len(argument) > int(self.telegram["max_prompt_length"]):
                raise AppError(ErrorCode.CONFIG_INVALID, "Prompt is empty or too long")
            return "Replace the configured prompt?", self._confirmation(user_id, chat_id, "setprompt", argument)
        if command in {"/timer", "/restarttimer"}:
            result = _service_action("background", "status" if command == "/timer" else "restart")
            return (json.dumps(result, ensure_ascii=False) if command == "/timer" else "Background service restarted."), None
        if command == "/version":
            from . import __version__

            return _pretty({"application_version": __version__}), None
        raise AppError(ErrorCode.CONFIG_INVALID, "Unknown command; use /help")

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        sender, message, data = callback.get("from"), callback.get("message"), callback.get("data")
        callback_id = str(callback.get("id", ""))
        if not isinstance(sender, dict) or not isinstance(message, dict) or not isinstance(data, str):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        user_id, chat_id, chat_type = int(sender.get("id", 0)), int(chat.get("id", 0)), str(chat.get("type", ""))
        if not self.authorized(user_id, chat_id, chat_type):
            self.api.answer_callback(callback_id, "Unauthorized")
            return
        decision, _, nonce = data.partition(":")
        state = load_state(self.paths)
        confirmation = state.get("telegram_confirmations", {}).get(nonce)
        if not isinstance(confirmation, dict):
            self.api.answer_callback(callback_id, "Expired")
            return
        valid = confirmation.get("user_id") == user_id and confirmation.get("chat_id") == chat_id and float(confirmation.get("expires", 0)) >= time.time()
        update_state(self.paths, lambda current: current.setdefault("telegram_confirmations", {}).pop(nonce, None))
        if not valid or decision not in {"confirm", "cancel"}:
            self.api.answer_callback(callback_id, "Expired")
            return
        if decision == "cancel":
            self.api.answer_callback(callback_id, "Cancelled")
            return
        action = str(confirmation["action"])
        if action == "run":
            _start_local_job("telegram")
        elif action == "setprompt":
            config = load_config(self.paths, create=True)
            config["prompt"] = str(confirmation.get("value", ""))
            save_config(self.paths, config)
        self.api.answer_callback(callback_id, "Started" if action == "run" else "Updated")

    def run_forever(self) -> None:
        if not self.telegram["enabled"]:
            raise AppError(ErrorCode.CONFIG_INVALID, "Telegram is disabled")
        self.api.get_me()
        with FileLock(self.paths.bot_lock, timeout=0, error_code=ErrorCode.ALREADY_RUNNING):
            while True:
                offset = int(load_state(self.paths).get("telegram_offset", 0))
                try:
                    self._drain_notifications()
                    for update in self.api.get_updates(offset):
                        update_id = int(update.get("update_id", offset))
                        self.handle_update(update)
                        update_state(self.paths, lambda state, value=update_id + 1: state.__setitem__("telegram_offset", value))
                except AppError as exc:
                    log_event(self.paths, {"status": "telegram_error", "error_code": exc.code.value, "sanitized_error": exc.message})
                    time.sleep(5)

    def _drain_notifications(self) -> None:
        state = load_state(self.paths)
        queue = state.get("notification_queue", [])
        if not isinstance(queue, list) or not queue:
            return
        target = self.telegram.get("notification_channel_id") or self.telegram.get("notification_chat_id")
        if type(target) is not int:
            return
        for item in queue[:10]:
            if isinstance(item, str):
                self.api.send_message(target, item)
        update_state(self.paths, lambda current: current.__setitem__("notification_queue", queue[10:]))


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _validate_time(value: str) -> None:
    try:
        datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise AppError(ErrorCode.CONFIG_INVALID, "Time must use HH:MM") from exc


def _start_local_job(trigger: str) -> None:
    import os

    launchctl = "/bin/launchctl"
    domain = f"gui/{os.getuid()}"
    process = subprocess.run(
        [launchctl, "kickstart", "-k", f"{domain}/com.openai.claude-window-starter.run-{trigger}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        shell=False,
    )
    if process.returncode != 0:
        raise AppError(ErrorCode.LAUNCHD_FAILED, "Unable to start local run service")


def _service_action(target: str, action: str) -> dict[str, Any]:
    import os

    label = f"com.openai.claude-window-starter.{target}"
    domain = f"gui/{os.getuid()}"
    if action == "status":
        argv = ["/bin/launchctl", "print", f"{domain}/{label}"]
    elif action == "stop":
        argv = ["/bin/launchctl", "kill", "SIGTERM", f"{domain}/{label}"]
    else:
        argv = ["/bin/launchctl", "kickstart", "-k", f"{domain}/{label}"]
    process = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10, check=False, shell=False)
    if process.returncode != 0:
        raise AppError(ErrorCode.LAUNCHD_FAILED, f"Unable to {action} {target} service")
    return {"label": label, "action": action, "output": process.stdout.strip()}


def notify(paths: AppPaths, text: str) -> None:
    config = load_config(paths, create=True)["telegram"]
    target = config.get("notification_channel_id") or config.get("notification_chat_id")
    if not config["enabled"] or type(target) is not int:
        return
    update_state(
        paths,
        lambda state: state.setdefault("notification_queue", []).append(text[:3900]),
    )
