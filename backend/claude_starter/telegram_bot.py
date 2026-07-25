from __future__ import annotations

import json
import secrets
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from .config import load_config, save_config
from .errors import AppError, ErrorCode
from .health import diagnose, health_report
from .locks import FileLock
from .logging_utils import log_event, tail_sanitized
from .paths import AppPaths
from .scheduler import next_runs
from .state import load_state, update_state
from .telegram_api import TelegramAPI

HELP = """🤖 Claude Window Starter

📊 Durum
/status — Sistem durumu ve pencere bilgisi
/usage — Sonraki çalışma zamanları
/last — Son çalışma detayı
/health — Sağlık kontrolü
/logs — Son kayıtlar

⚡ Otomasyon
/run — Claude çalıştır (onay ister)
/automation_on / /automation_off — Otomasyonu aç/kapat
/sleep_on / /sleep_off — Uyku engellemeyi aç/kapat

🗓 Kalibrasyon
/calibrate_5h HH:MM — 5 saatlik pencereyi ayarla
/calibrate_5h YYYY-MM-DD HH:MM
/calibrate_weekly YYYY-MM-DD HH:MM

⚙️ Ayarlar
/setmodel <auto|haiku|sonnet|opus>
/setprompt <metin>
/settimezone <iana>

👥 Kullanıcı Yönetimi
/users — Yetkili kullanıcıları listele
/adduser <id> — Kullanıcı ekle
/removeuser <id> — Kullanıcı kaldır

/help — Bu menü"""


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
            # Private chat is always 1:1 between user and bot; user_id check is sufficient.
            return True
        return chat_id in self.telegram["allowed_chat_ids"]

    def _rate_allowed(self, user_id: int) -> bool:
        now = time.time()
        cooldown = int(self.telegram["command_cooldown_seconds"])
        state = load_state(self.paths)
        previous = float(state.get("telegram_rate_limits", {}).get(str(user_id), 0))
        if now - previous < cooldown:
            return False

        def record_rate_limit(current: dict[str, Any]) -> None:
            current.setdefault("telegram_rate_limits", {})[str(user_id)] = now

        update_state(self.paths, record_rate_limit)
        return True

    def _confirmation(
        self, user_id: int, chat_id: int, action: str, value: str = ""
    ) -> dict[str, Any]:
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
        return {
            "inline_keyboard": [
                [
                    {"text": "Confirm", "callback_data": f"confirm:{nonce}"},
                    {"text": "Cancel", "callback_data": f"cancel:{nonce}"},
                ]
            ]
        }

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
        user_id, chat_id, chat_type = (
            int(sender.get("id", 0)),
            int(chat.get("id", 0)),
            str(chat.get("type", "")),
        )
        if not self.authorized(user_id, chat_id, chat_type):
            log_event(
                self.paths,
                {"status": "unauthorized", "error_code": ErrorCode.TELEGRAM_UNAUTHORIZED.value},
            )
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

    def _command(
        self, command: str, argument: str, user_id: int, chat_id: int
    ) -> tuple[str, dict[str, Any] | None]:
        self.config = load_config(self.paths, create=True)
        self.telegram = self.config["telegram"]
        state = load_state(self.paths)
        if command == "/help":
            return HELP, None
        if command == "/status":
            enabled = "✅ Açık" if self.config["enabled"] else "❌ Kapalı"
            bg = "✅ Açık" if self.config["background_enabled"] else "❌ Kapalı"
            tz = self.config["timezone"]
            health = health_report(self.paths)
            ok = health.get("ok", False)
            health_str = "✅ Sağlıklı" if ok else "⚠️ Sorun var"
            last = state.get("last_run")
            last_str = ""
            if isinstance(last, dict):
                last_str = f"\n🕐 Son çalışma: {last.get('trigger_time','?')[:16]} — {last.get('status','?')}"
            next_windows = next_runs(self.paths, self.config)
            window_lines = []
            for wtype, dt in next_windows.items():
                label = "5 saatlik" if wtype == "five_hour" else "Haftalık"
                window_lines.append(f"  • {label}: {dt.strftime('%d.%m.%Y %H:%M')} UTC")
            windows_str = "\n".join(window_lines) if window_lines else "  • Pencere tanımlı değil"
            return (
                f"📊 *Sistem Durumu*\n"
                f"Otomasyon: {enabled}\n"
                f"Uyku önleme: {bg}\n"
                f"Zaman dilimi: {tz}\n"
                f"Sağlık: {health_str}\n"
                f"Sonraki çalışmalar:\n{windows_str}{last_str}"
            ), None
        if command == "/start":
            _service_action("background", "start")
            self.config["enabled"] = True
            save_config(self.paths, self.config)
            return "Automation enabled and background service started.", None
        if command == "/stop":
            _service_action("background", "stop")
            self.config["enabled"] = False
            save_config(self.paths, self.config)
            return "Automation disabled and background service stopped.", None
        if command == "/restart":
            _service_action("background", "restart")
            return "Background service restarted.", None
        if command == "/run":
            return "Run a real Claude subscription request?", self._confirmation(
                user_id, chat_id, "run"
            )
        if command == "/automation_on":
            self.config["enabled"] = True
            save_config(self.paths, self.config)
            return "Automation enabled.", None
        if command == "/automation_off":
            self.config["enabled"] = False
            save_config(self.paths, self.config)
            return "Automation disabled.", None
        if command in {"/background_on", "/sleep_on"}:
            self.config["background_enabled"] = True
            save_config(self.paths, self.config)
            return "Background sleep-prevention mode enabled.", None
        if command in {"/background_off", "/sleep_off"}:
            self.config["background_enabled"] = False
            save_config(self.paths, self.config)
            return "Background sleep-prevention mode disabled.", None
        if command == "/usage":
            next_window = next_runs(self.paths, self.config)
            lines = ["📅 *Pencere Durumu*"]
            for wtype, dt in next_window.items():
                label = "5 saatlik" if wtype == "five_hour" else "Haftalık"
                lines.append(f"  • {label}: {dt.strftime('%d.%m.%Y %H:%M')} UTC")
            if not next_window:
                lines.append("  • Pencere tanımlı değil")
            last = state.get("last_run")
            if isinstance(last, dict):
                lines.append(f"\n🕐 Son çalışma: {last.get('trigger_time','?')[:16]} — {last.get('status','?')}")
            return "\n".join(lines), None
        if command == "/maintenance":
            health = health_report(self.paths)
            diag = diagnose(self.paths)
            ok = "✅ Sağlıklı" if health.get("ok") else "⚠️ Sorun var"
            issues = [k for k, v in health.get("checks", {}).items() if isinstance(v, dict) and not v.get("ok", True)]
            issues_str = ", ".join(issues) if issues else "—"
            return f"🔧 *Bakım Raporu*\nSağlık: {ok}\nSorunlar: {issues_str}", None
        if command == "/dryrun":
            _start_local_job("dry")
            return "🧪 Kuru çalışma başlatıldı — Claude'a gerçek istek gönderilmeyecek.", None
        if command == "/diagnose":
            diag = diagnose(self.paths)
            lines = ["🔍 *Teşhis*"]
            for k, v in diag.items():
                lines.append(f"  • {k}: {v}")
            return "\n".join(lines[:20]), None
        if command == "/health":
            health = health_report(self.paths)
            ok = "✅ Sağlıklı" if health.get("ok") else "⚠️ Sorun var"
            lines = [f"💚 Sağlık: {ok}"]
            for k, v in health.get("checks", {}).items():
                if isinstance(v, dict):
                    status = "✅" if v.get("ok", False) else "❌"
                    lines.append(f"  {status} {k}")
            return "\n".join(lines), None
        if command == "/schedule":
            next_window = next_runs(self.paths, self.config)
            if not next_window:
                return "📅 Pencere tanımlı değil", None
            lines = ["📅 *Sonraki Çalışmalar*"]
            for wtype, dt in next_window.items():
                label = "5 saatlik" if wtype == "five_hour" else "Haftalık"
                lines.append(f"  • {label}: {dt.strftime('%d.%m.%Y %H:%M')} UTC")
            return "\n".join(lines), None
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
            return f"Timezone updated to {argument}.", None
        if command in {"/enable", "/disable"}:
            self.config["enabled"] = command == "/enable"
            save_config(self.paths, self.config)
            return f"Automation {'enabled' if self.config['enabled'] else 'disabled'}.", None
        if command == "/background":
            if argument not in {"on", "off"}:
                raise AppError(ErrorCode.CONFIG_INVALID, "Use /background on or /background off")
            self.config["background_enabled"] = argument == "on"
            save_config(self.paths, self.config)
            background_status = "enabled" if self.config["background_enabled"] else "disabled"
            return (
                f"Background mode {background_status}.",
                None,
            )
        if command == "/next":
            next_window = next_runs(self.paths, self.config)
            if not next_window:
                return "📅 Zamanlanmış pencere yok", None
            lines = ["📅 *Sonraki Çalışmalar*"]
            for wtype, dt in next_window.items():
                label = "5 saatlik" if wtype == "five_hour" else "Haftalık"
                lines.append(f"  • {label}: {dt.strftime('%d.%m.%Y %H:%M')} UTC")
            return "\n".join(lines), None
        if command == "/last":
            last = state.get("last_run")
            if not isinstance(last, dict):
                return "ℹ️ Henüz çalışma yok", None
            status_icon = "✅" if last.get("status") == "success" else "❌"
            model = last.get("selected_model", "?")
            trigger = last.get("trigger_source", "?")
            time_str = str(last.get("trigger_time", "?"))[:16]
            return f"{status_icon} *Son Çalışma*\nZaman: {time_str}\nModel: {model}\nTetikleyici: {trigger}", None
        if command == "/logs":
            return "\n".join(tail_sanitized(self.paths.log_file, 15)) or "No logs.", None
        if command == "/model":
            return str(self.config["model"]), None
        if command == "/setmodel":
            if argument not in {"auto", "haiku", "sonnet", "opus"}:
                raise AppError(
                    ErrorCode.CONFIG_INVALID, "Model must be auto, haiku, sonnet, or opus"
                )
            self.config["model"] = argument
            save_config(self.paths, self.config)
            return f"Model set to {argument}.", None
        if command == "/prompt":
            return str(self.config["prompt"]), None
        if command == "/setprompt":
            if not argument or len(argument) > int(self.telegram["max_prompt_length"]):
                raise AppError(ErrorCode.CONFIG_INVALID, "Prompt is empty or too long")
            return "Replace the configured prompt?", self._confirmation(
                user_id, chat_id, "setprompt", argument
            )
        if command in {"/timer", "/restarttimer"}:
            if command == "/restarttimer":
                _service_action("background", "restart")
                return "♻️ Arka plan servisi yeniden başlatıldı.", None
            try:
                _service_action("background", "status")
                return "✅ Arka plan servisi çalışıyor.", None
            except AppError:
                return "❌ Arka plan servisi çalışmıyor.", None
        if command == "/users":
            uids = self.telegram.get("allowed_user_ids", [])
            cids = self.telegram.get("allowed_chat_ids", [])
            user_lines = "\n".join(f"  • {u}" for u in uids) if uids else "  • Yok"
            chat_lines = "\n".join(f"  • {c}" for c in cids) if cids else "  • Yok"
            return f"👥 *Yetkili Kullanıcılar*\n{user_lines}\n\n💬 *Yetkili Sohbetler*\n{chat_lines}", None
        if command == "/adduser":
            if not argument.strip().lstrip("-").isdigit():
                raise AppError(ErrorCode.CONFIG_INVALID, "Usage: /adduser <numeric_user_id>")
            uid = int(argument.strip())
            ids = self.config["telegram"].setdefault("allowed_user_ids", [])
            if uid not in ids:
                ids.append(uid)
                save_config(self.paths, self.config)
                return f"User {uid} added.", None
            return f"User {uid} already authorized.", None
        if command == "/removeuser":
            if not argument.strip().lstrip("-").isdigit():
                raise AppError(ErrorCode.CONFIG_INVALID, "Usage: /removeuser <numeric_user_id>")
            uid = int(argument.strip())
            ids = self.config["telegram"].get("allowed_user_ids", [])
            if uid in ids:
                self.config["telegram"]["allowed_user_ids"] = [x for x in ids if x != uid]
                save_config(self.paths, self.config)
                return f"User {uid} removed.", None
            return f"User {uid} was not authorized.", None
        if command == "/addchat":
            if not argument.strip().lstrip("-").isdigit():
                raise AppError(ErrorCode.CONFIG_INVALID, "Usage: /addchat <numeric_chat_id>")
            cid = int(argument.strip())
            ids = self.config["telegram"].setdefault("allowed_chat_ids", [])
            if cid not in ids:
                ids.append(cid)
                save_config(self.paths, self.config)
                return f"Chat {cid} added.", None
            return f"Chat {cid} already authorized.", None
        if command == "/removechat":
            if not argument.strip().lstrip("-").isdigit():
                raise AppError(ErrorCode.CONFIG_INVALID, "Usage: /removechat <numeric_chat_id>")
            cid = int(argument.strip())
            ids = self.config["telegram"].get("allowed_chat_ids", [])
            if cid in ids:
                self.config["telegram"]["allowed_chat_ids"] = [x for x in ids if x != cid]
                save_config(self.paths, self.config)
                return f"Chat {cid} removed.", None
            return f"Chat {cid} was not authorized.", None
        if command == "/calibrate_5h":
            return self._calibrate_window("five_hour", argument, user_id, chat_id)
        if command == "/calibrate_weekly":
            return self._calibrate_window("weekly", argument, user_id, chat_id)
        if command == "/version":
            from . import __version__

            return _pretty({"application_version": __version__}), None
        raise AppError(ErrorCode.CONFIG_INVALID, "Unknown command; use /help")

    def _calibrate_window(
        self, window_type: str, argument: str, user_id: int, chat_id: int
    ) -> tuple[str, dict[str, Any] | None]:
        """Parse calibration argument and run calibrate command."""
        from zoneinfo import ZoneInfo

        if not argument.strip():
            raise AppError(ErrorCode.CONFIG_INVALID, f"Usage: /calibrate_{window_type.split('_')[0]} HH:MM or YYYY-MM-DD HH:MM")

        parts = argument.strip().split()
        user_tz = ZoneInfo(self.config.get("timezone", "UTC"))

        try:
            if len(parts) == 1:
                # Format: HH:MM — use today's date
                time_str = parts[0]
                if not _is_valid_time(time_str):
                    raise ValueError("Invalid time format")
                today = datetime.now(tz=user_tz).date()
                dt_local = datetime.combine(today, datetime.strptime(time_str, "%H:%M").time())
                dt_with_tz = dt_local.replace(tzinfo=user_tz)
            elif len(parts) == 2:
                # Format: YYYY-MM-DD HH:MM
                date_str, time_str = parts
                if not _is_valid_datetime(f"{date_str} {time_str}"):
                    raise ValueError("Invalid datetime format")
                dt_local = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
                dt_with_tz = dt_local.replace(tzinfo=user_tz)
            else:
                raise ValueError("Invalid format")

            # Convert to UTC ISO format
            dt_utc = dt_with_tz.astimezone(timezone.utc)
            anchor_iso = dt_utc.isoformat()

            # Call calibrate CLI command
            _run_calibrate_cli(self.paths, window_type, anchor_iso)

            # Get updated next_run_at
            next_window = next_runs(self.paths, self.config)
            next_at = next_window.get(window_type)
            next_iso = next_at.isoformat() if next_at else "unknown"

            return f"✓ {window_type} penceresi kalibre edildi.\nAnchor: {anchor_iso}\nSonraki çalışma: {next_iso}", None
        except ValueError as exc:
            raise AppError(ErrorCode.CONFIG_INVALID, f"Invalid time format: {str(exc)}")

    def _handle_callback(self, callback: dict[str, Any]) -> None:
        sender, message, data = callback.get("from"), callback.get("message"), callback.get("data")
        callback_id = str(callback.get("id", ""))
        if (
            not isinstance(sender, dict)
            or not isinstance(message, dict)
            or not isinstance(data, str)
        ):
            return
        chat = message.get("chat")
        if not isinstance(chat, dict):
            return
        user_id, chat_id, chat_type = (
            int(sender.get("id", 0)),
            int(chat.get("id", 0)),
            str(chat.get("type", "")),
        )
        if not self.authorized(user_id, chat_id, chat_type):
            self.api.answer_callback(callback_id, "Unauthorized")
            return
        decision, _, nonce = data.partition(":")
        state = load_state(self.paths)
        confirmation = state.get("telegram_confirmations", {}).get(nonce)
        if not isinstance(confirmation, dict):
            self.api.answer_callback(callback_id, "Expired")
            return
        expires = confirmation.get("expires")
        expires_at = float(expires) if isinstance(expires, int | float) else 0.0
        valid = (
            confirmation.get("user_id") == user_id
            and confirmation.get("chat_id") == chat_id
            and expires_at >= time.time()
        )
        update_state(
            self.paths,
            lambda current: current.setdefault("telegram_confirmations", {}).pop(nonce, None),
        )
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

                        def save_offset(state: dict[str, Any], value: int = update_id + 1) -> None:
                            state["telegram_offset"] = value

                        update_state(self.paths, save_offset)
                except AppError as exc:
                    log_event(
                        self.paths,
                        {
                            "status": "telegram_error",
                            "error_code": exc.code.value,
                            "sanitized_error": exc.message,
                        },
                    )
                    time.sleep(5)
                except Exception as exc:
                    log_event(
                        self.paths,
                        {
                            "status": "telegram_unexpected_error",
                            "sanitized_error": str(exc)[:200],
                        },
                    )
                    time.sleep(5)

    def _drain_notifications(self) -> None:
        target = self.telegram.get("notification_channel_id") or self.telegram.get(
            "notification_chat_id"
        )
        if type(target) is not int:
            return
        state = load_state(self.paths)
        queue = state.get("notification_queue", [])
        if not isinstance(queue, list) or not queue:
            return
        batch = queue[:10]
        batch_size = len(batch)
        for item in batch:
            if isinstance(item, str):
                self.api.send_message(target, item)
        # Advance the queue by batch_size inside update_state so that items appended
        # by notify() between our read above and this write are never overwritten.
        update_state(
            self.paths,
            lambda current: current.__setitem__(
                "notification_queue",
                (current.get("notification_queue") or [])[batch_size:],
            ),
        )


def _pretty(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)


def _is_valid_time(value: str) -> bool:
    """Check if value is in HH:MM format."""
    try:
        datetime.strptime(value, "%H:%M")
        return True
    except ValueError:
        return False


def _is_valid_datetime(value: str) -> bool:
    """Check if value is in YYYY-MM-DD HH:MM format."""
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M")
        return True
    except ValueError:
        return False


def _run_calibrate_cli(paths: AppPaths, window_type: str, anchor_iso: str) -> None:
    """Run the calibrate CLI command."""
    import subprocess

    try:
        result = subprocess.run(
            [
                "python3",
                "-m",
                "claude_starter",
                "--home",
                str(paths.base),
                "calibrate",
                "--window-type",
                window_type,
                "--anchor",
                anchor_iso,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            stderr = result.stderr or result.stdout or "Unknown error"
            raise AppError(ErrorCode.CONFIG_INVALID, f"Calibrate failed: {stderr[:200]}")
    except subprocess.TimeoutExpired as exc:
        raise AppError(ErrorCode.CONFIG_INVALID, "Calibrate command timed out") from exc


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
    elif action == "start":
        argv = ["/bin/launchctl", "kickstart", f"{domain}/{label}"]
    else:
        argv = ["/bin/launchctl", "kickstart", "-k", f"{domain}/{label}"]
    process = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        shell=False,
    )
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
