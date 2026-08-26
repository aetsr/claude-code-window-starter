from __future__ import annotations

import os
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
from .scheduler import next_runs, schedule_snapshot
from .service_utils import kickstart_local_job, service_action
from .state import load_state, update_state
from .telegram_api import TelegramAPI
from .usage import query_usage

WELCOME = (
    "🤖 *Claude Window Starter*\n\n"
    "Merhaba\\! Bu bot, Claude Code abonelik isteklerinizi\n"
    "5 saatlik kullanım pencerelerinde otomatik olarak yönetir\\.\n\n"
    "Başlamak için:\n"
    "• /status — Mevcut durumu görüntüle\n"
    "• /automation\\_on — Otomasyonu etkinleştir\n"
    "• /help — Tüm komutları listele"
)

HELP = """🤖 *Claude Window Starter*

📊 *Durum*
/status — Sistem durumu ve pencere bilgisi
/usage — Kullanım bilgisini getir
/sync_usage — Kullanımı yeniden ölç ve planı güncelle
/schedule — Sonraki çalışma zamanları
/last — Son çalışma detayı
/health — Sağlık kontrolü
/logs — Son kayıtlar
/ping — Bot canlılık kontrolü

⚡ *Otomasyon*
/run — Claude çalıştır (onay ister)
/dryrun — Kuru çalışma (gerçek istek yok)
/automation\\_on / /automation\\_off — Otomasyonu aç/kapat
/sleep\\_on / /sleep\\_off — Uyku engellemeyi aç/kapat

🗓 *Kalibrasyon*
/calibrate\\_5h HH:MM — 5 saatlik pencereyi ayarla
/calibrate\\_weekly YYYY\\-MM\\-DD HH:MM

⚙️ *Ayarlar*
/setmodel <auto|haiku|sonnet|opus>
/setprompt <metin>
/settimezone <iana>
/workhours HH:MM HH:MM — Yoğun çalışma aralığını ayarla

👥 *Kullanıcı Yönetimi*
/users — Yetkili kullanıcıları listele
/adduser <id> — Kullanıcı ekle
/removeuser <id> — Kullanıcı kaldır"""

_ALIASES: dict[str, str] = {
    "/next": "/schedule",
    "/enable": "/automation_on",
    "/disable": "/automation_off",
    "/restarttimer": "/restart",
}


def _md_escape(s: str) -> str:
    """Escape Markdown special characters in dynamic values."""
    return s.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")


def _fmt_dt(dt: Any, tz_name: str = "UTC") -> str:
    """Format a datetime or ISO string to human-readable Turkish format."""
    from zoneinfo import ZoneInfo

    MONTHS = [
        "Ocak",
        "Şubat",
        "Mart",
        "Nisan",
        "Mayıs",
        "Haziran",
        "Temmuz",
        "Ağustos",
        "Eylül",
        "Ekim",
        "Kasım",
        "Aralık",
    ]
    if dt is None:
        return "bilinmiyor"
    if isinstance(dt, str):
        try:
            from .windows import _parse_iso

            dt = _parse_iso(dt)
        except Exception:
            return dt[:16]
    try:
        local = dt.astimezone(ZoneInfo(tz_name))
        month = MONTHS[local.month - 1]
        place = tz_name.split("/")[-1]
        base = f"{local.day} {month} {local.year}, {local.strftime('%H:%M')} ({place})"
        # Also show Turkey time when primary timezone is not Istanbul.
        if tz_name != "Europe/Istanbul":
            tr = dt.astimezone(ZoneInfo("Europe/Istanbul"))
            base += f" / {tr.strftime('%H:%M')} TR"
        return base
    except Exception:
        return str(dt)[:16]


class TelegramBot:
    def __init__(
        self,
        paths: AppPaths,
        api: TelegramAPI | None = None,
        token: str = "",
        supervisor_pid: int | None = None,
    ) -> None:
        self.paths = paths
        self.config = load_config(paths, create=True)
        self.telegram = self.config["telegram"]
        self.api = api or TelegramAPI(token)
        self.supervisor_pid = supervisor_pid

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
                    {"text": "✅ Onayla", "callback_data": f"confirm:{nonce}"},
                    {"text": "❌ İptal", "callback_data": f"cancel:{nonce}"},
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
            self.api.send_message(
                chat_id,
                "Bu komut için yetkiniz yok.",
                auto_parse_mode=False,
            )
            return
        if not self._rate_allowed(user_id):
            self.api.send_message(
                chat_id,
                "Lütfen birkaç saniye sonra tekrar deneyin.",
                auto_parse_mode=False,
            )
            return
        command, _, argument = text.strip().partition(" ")
        command = command.split("@", 1)[0].lower()
        try:
            if command in {
                "/usage",
                "/sync_usage",
                "/run",
                "/health",
                "/diagnose",
                "/maintenance",
                "/dryrun",
            }:
                self.api.send_chat_action(chat_id, "typing")
            response, markup = self._command(command, argument.strip(), user_id, chat_id)
            self.api.send_message(
                chat_id,
                response,
                reply_markup=markup,
                auto_parse_mode=command not in {"/usage", "/sync_usage"},
            )
        except AppError as exc:
            response = (
                _usage_error_message(exc)
                if command in {"/usage", "/sync_usage"}
                else f"{exc.code.value}: {exc.message}"
            )
            self.api.send_message(chat_id, response, auto_parse_mode=False)
        except Exception as exc:
            log_event(
                self.paths,
                {
                    "status": "telegram_unhandled_error",
                    "command": command,
                    "sanitized_error": str(exc)[:200],
                },
            )
            self.api.send_message(
                chat_id,
                "Bir hata oluştu. Lütfen tekrar deneyin.",
                auto_parse_mode=False,
            )

    def _command(
        self, command: str, argument: str, user_id: int, chat_id: int
    ) -> tuple[str, dict[str, Any] | None]:
        self.config = load_config(self.paths, create=True)
        self.telegram = self.config["telegram"]
        state = load_state(self.paths)
        command = _ALIASES.get(command, command)
        if command == "/start":
            return WELCOME, None
        if command == "/help":
            return HELP, None
        if command == "/ping":
            from zoneinfo import ZoneInfo

            now = datetime.now(ZoneInfo(self.config.get("timezone", "UTC")))
            return f"pong — {now.strftime('%d.%m.%Y %H:%M')}", None
        if command == "/status":
            return self._cmd_status(state), None
        if command == "/stop":
            service_action("background", "stop")
            self.config["enabled"] = False
            save_config(self.paths, self.config)
            return "⏹ Otomasyon devre dışı bırakıldı ve arka plan servisi durduruldu.", None
        if command == "/restart":
            service_action("background", "restart")
            return "♻️ Arka plan servisi yeniden başlatıldı.", None
        if command == "/run":
            return (
                "🤖 Claude çalıştırılsın mı? Gerçek bir API isteği gönderilecek.",
                self._confirmation(user_id, chat_id, "run"),
            )
        if command == "/automation_on":
            self.config["enabled"] = True
            save_config(self.paths, self.config)
            return "✅ Otomasyon etkinleştirildi.", None
        if command == "/automation_off":
            self.config["enabled"] = False
            save_config(self.paths, self.config)
            return "⏸ Otomasyon devre dışı bırakıldı.", None
        if command in {"/background_on", "/sleep_on"}:
            self.config["background_enabled"] = True
            save_config(self.paths, self.config)
            return "🌙 Uyku engelleme modu etkinleştirildi.", None
        if command in {"/background_off", "/sleep_off"}:
            self.config["background_enabled"] = False
            save_config(self.paths, self.config)
            return "☀️ Uyku engelleme modu kapatıldı.", None
        if command == "/usage":
            return query_usage(self.paths, self.config).get(
                "formatted_text", "Claude kullanım bilgisi alınamadı."
            ), None
        if command == "/sync_usage":
            usage = query_usage(self.paths, self.config)
            schedule = schedule_snapshot(self.paths, self.config)
            next_at = _fmt_dt(schedule.get("next_action_at"), self.config["timezone"])
            return (
                f"{usage.get('formatted_text', 'Kullanım senkronize edildi.')}\n\n"
                f"Plan güveni: {schedule['confidence']}\nSonraki eylem: {next_at}"
            ), None
        if command == "/maintenance":
            health = health_report(self.paths)
            diag = diagnose(self.paths)
            ok = "✅ Sağlıklı" if health.get("ok") else "⚠️ Sorun var"
            issues = [
                k
                for k, v in health.get("checks", {}).items()
                if isinstance(v, dict) and not v.get("ok", True)
            ]
            issues_str = ", ".join(issues) if issues else "—"
            return f"🔧 *Bakım Raporu*\nSağlık: {ok}\nSorunlar: {_md_escape(issues_str)}", None
        if command == "/dryrun":
            kickstart_local_job("dry")
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
            schedule = schedule_snapshot(self.paths, self.config)
            busy = schedule["busy_period"]
            lines = [
                "📅 *Adaptif Plan*",
                (
                    f"Yoğun aralık: {busy['start_local']}–{busy['end_local']} "
                    f"({_md_escape(busy['timezone'])})"
                ),
                f"Durum: {_md_escape(str(schedule['status']))}",
                f"Güven: {_md_escape(str(schedule['confidence']))}",
            ]
            observed = schedule.get("observed_window")
            if isinstance(observed, dict) and observed.get("resets_at"):
                display = _fmt_dt(observed["resets_at"], self.config["timezone"])
                lines.append(f"Gözlenen reset: {_md_escape(display)}")
            actions = schedule.get("today_actions", [])
            if actions:
                lines.append("Bugünkü anchorlar:")
                for action in actions:
                    marker = "✓" if action.get("status") != "planned" else "•"
                    display = _fmt_dt(action.get("scheduled_at"), self.config["timezone"])
                    lines.append(
                        f"  {marker} {_md_escape(display)} — "
                        f"{_md_escape(str(action.get('status')))}"
                    )
            else:
                lines.append("Bugün planlı anchor yok.")
            next_display = _fmt_dt(schedule.get("next_action_at"), self.config["timezone"])
            lines.append(f"Sonraki: {_md_escape(next_display)}")
            return "\n".join(lines), None
        if command == "/workhours":
            parts = argument.split()
            if len(parts) != 2 or not all(_is_valid_time(value) for value in parts):
                raise AppError(ErrorCode.CONFIG_INVALID, "Kullanım: /workhours HH:MM HH:MM")
            start, end = parts
            if datetime.strptime(start, "%H:%M") >= datetime.strptime(end, "%H:%M"):
                raise AppError(
                    ErrorCode.CONFIG_INVALID,
                    "Başlangıç bitişten önce olmalı; gece yarısını geçen aralık desteklenmiyor.",
                )
            five_hour = self.config["windows"]["five_hour"]
            five_hour["mode"] = "adaptive"
            five_hour["busy_start_local"] = start
            five_hour["busy_end_local"] = end
            save_config(self.paths, self.config)
            update_state(self.paths, lambda value: value.__setitem__("adaptive_plan", None))
            schedule = schedule_snapshot(self.paths, self.config)
            next_display = _fmt_dt(schedule.get("next_action_at"), self.config["timezone"])
            return (
                f"✅ Yoğun çalışma aralığı {start}–{end} olarak güncellendi.\n"
                f"Hafta içi / Maksimum kota\nSonraki anchor: {next_display}"
            ), None
        if command == "/timezone":
            return f"🌍 Zaman dilimi: *{self.config['timezone']}*", None
        if command == "/settimezone":
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

            try:
                ZoneInfo(argument)
            except ZoneInfoNotFoundError as exc:
                raise AppError(ErrorCode.CONFIG_INVALID, "Geçersiz IANA zaman dilimi") from exc
            self.config["timezone"] = argument
            save_config(self.paths, self.config)
            return f"✅ Zaman dilimi *{_md_escape(argument)}* olarak güncellendi.", None
        if command == "/background":
            if argument not in {"on", "off"}:
                raise AppError(
                    ErrorCode.CONFIG_INVALID, "Kullanım: /background on veya /background off"
                )
            self.config["background_enabled"] = argument == "on"
            save_config(self.paths, self.config)
            return (
                "🌙 Uyku engelleme etkinleştirildi."
                if self.config["background_enabled"]
                else "☀️ Uyku engelleme kapatıldı."
            ), None
        if command == "/last":
            last = state.get("last_run")
            if not isinstance(last, dict):
                return "ℹ️ Henüz çalışma yok", None
            status_icon = "✅" if last.get("status") == "success" else "❌"
            model = last.get("selected_model", "?")
            trigger = last.get("trigger_source", "?")
            time_str = str(last.get("trigger_time", "?"))[:16]
            return (
                f"{status_icon} *Son Çalışma*\n"
                f"Zaman: {_md_escape(time_str)}\n"
                f"Model: {_md_escape(str(model))}\n"
                f"Tetikleyici: {_md_escape(str(trigger))}",
                None,
            )
        if command == "/logs":
            return "\n".join(tail_sanitized(self.paths.log_file, 15)) or "No logs.", None
        if command == "/model":
            return f"🤖 Aktif model: *{self.config['model']}*", None
        if command == "/setmodel":
            if argument not in {"auto", "haiku", "sonnet", "opus"}:
                raise AppError(
                    ErrorCode.CONFIG_INVALID, "Geçerli modeller: auto, haiku, sonnet, opus"
                )
            self.config["model"] = argument
            save_config(self.paths, self.config)
            return f"✅ Model *{_md_escape(argument)}* olarak ayarlandı.", None
        if command == "/prompt":
            return f"📝 Mevcut prompt:\n\n{self.config['prompt'][:400]}", None
        if command == "/setprompt":
            if not argument or len(argument) > int(self.telegram["max_prompt_length"]):
                raise AppError(ErrorCode.CONFIG_INVALID, "Prompt boş veya çok uzun.")
            return f"📝 Prompt şununla değiştirilsin mi?\n\n_{argument[:200]}_", self._confirmation(
                user_id, chat_id, "setprompt", argument
            )
        if command == "/timer":
            try:
                service_action("background", "status")
                return "✅ Arka plan servisi çalışıyor.", None
            except AppError:
                return "❌ Arka plan servisi çalışmıyor.", None
        if command == "/users":
            uids = self.telegram.get("allowed_user_ids", [])
            cids = self.telegram.get("allowed_chat_ids", [])
            user_lines = "\n".join(f"  • {u}" for u in uids) if uids else "  • Yok"
            chat_lines = "\n".join(f"  • {c}" for c in cids) if cids else "  • Yok"
            return (
                f"👥 *Yetkili Kullanıcılar*\n{user_lines}\n\n💬 *Yetkili Sohbetler*\n{chat_lines}",
                None,
            )
        if command == "/adduser":
            if not argument.strip().lstrip("-").isdigit():
                raise AppError(
                    ErrorCode.CONFIG_INVALID, "Kullanım: /adduser <sayısal kullanıcı ID>"
                )
            uid = int(argument.strip())
            ids = self.config["telegram"].setdefault("allowed_user_ids", [])
            if uid not in ids:
                ids.append(uid)
                save_config(self.paths, self.config)
                return f"✅ Kullanıcı {uid} eklendi.", None
            return f"ℹ️ Kullanıcı {uid} zaten yetkili.", None
        if command == "/removeuser":
            if not argument.strip().lstrip("-").isdigit():
                raise AppError(
                    ErrorCode.CONFIG_INVALID, "Kullanım: /removeuser <sayısal kullanıcı ID>"
                )
            uid = int(argument.strip())
            ids = self.config["telegram"].get("allowed_user_ids", [])
            if uid in ids:
                self.config["telegram"]["allowed_user_ids"] = [x for x in ids if x != uid]
                save_config(self.paths, self.config)
                return f"🗑 Kullanıcı {uid} kaldırıldı.", None
            return f"ℹ️ Kullanıcı {uid} listede değildi.", None
        if command == "/addchat":
            if not argument.strip().lstrip("-").isdigit():
                raise AppError(ErrorCode.CONFIG_INVALID, "Kullanım: /addchat <sayısal sohbet ID>")
            cid = int(argument.strip())
            ids = self.config["telegram"].setdefault("allowed_chat_ids", [])
            if cid not in ids:
                ids.append(cid)
                save_config(self.paths, self.config)
                return f"✅ Sohbet {cid} eklendi.", None
            return f"ℹ️ Sohbet {cid} zaten yetkili.", None
        if command == "/removechat":
            if not argument.strip().lstrip("-").isdigit():
                raise AppError(
                    ErrorCode.CONFIG_INVALID, "Kullanım: /removechat <sayısal sohbet ID>"
                )
            cid = int(argument.strip())
            ids = self.config["telegram"].get("allowed_chat_ids", [])
            if cid in ids:
                self.config["telegram"]["allowed_chat_ids"] = [x for x in ids if x != cid]
                save_config(self.paths, self.config)
                return f"🗑 Sohbet {cid} kaldırıldı.", None
            return f"ℹ️ Sohbet {cid} listede değildi.", None
        if command == "/calibrate_5h":
            return self._calibrate_window("five_hour", argument, user_id, chat_id)
        if command == "/calibrate_weekly":
            return self._calibrate_window("weekly", argument, user_id, chat_id)
        if command == "/version":
            from . import __version__

            return f"ℹ️ Claude Window Starter *{__version__}*", None
        raise AppError(
            ErrorCode.CONFIG_INVALID, "Bilinmeyen komut — /help ile komut listesini görüntüle"
        )

    def _calibrate_window(
        self, window_type: str, argument: str, user_id: int, chat_id: int
    ) -> tuple[str, dict[str, Any] | None]:
        """Parse calibration argument and run calibrate command."""
        from zoneinfo import ZoneInfo

        if not argument.strip():
            wname = window_type.split("_")[0]
            raise AppError(
                ErrorCode.CONFIG_INVALID,
                f"Kullanım: /calibrate_{wname} HH:MM veya YYYY-MM-DD HH:MM",
            )

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
            label = "5 saatlik" if window_type == "five_hour" else "Haftalık"
            user_tz = self.config.get("timezone", "UTC")
            next_display = _fmt_dt(next_at, user_tz) if next_at else "hesaplanamadı"
            anchor_display = _fmt_dt(anchor_iso, user_tz)
            return (
                f"✅ *{label} pencere kalibre edildi*\n"
                f"Başlangıç: {anchor_display}\n"
                f"Sonraki çalışma: {next_display}"
            ), None
        except ValueError as exc:
            raise AppError(
                ErrorCode.CONFIG_INVALID,
                f"Geçersiz zaman formatı: {exc}",
            ) from exc

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
        message_id = int(message.get("message_id", 0))
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
            self.api.answer_callback(callback_id, "⏱ Süre doldu")
            if message_id:
                self.api.edit_message_text(chat_id, message_id, "⏱ Süre doldu.")
            return
        if decision == "cancel":
            self.api.answer_callback(callback_id, "❌ İptal edildi")
            if message_id:
                self.api.edit_message_text(chat_id, message_id, "❌ İptal edildi.")
            return
        action = str(confirmation["action"])
        if action == "run":
            kickstart_local_job("telegram")
        elif action == "setprompt":
            config = load_config(self.paths, create=True)
            config["prompt"] = str(confirmation.get("value", ""))
            save_config(self.paths, config)
        result_text = "🚀 Başlatıldı" if action == "run" else "✅ Güncellendi"
        self.api.answer_callback(callback_id, result_text)
        if message_id:
            self.api.edit_message_text(chat_id, message_id, f"{result_text}.")

    def run_forever(self) -> None:
        if not self.telegram["enabled"]:
            raise AppError(ErrorCode.CONFIG_INVALID, "Telegram is disabled")
        if not self._supervisor_alive():
            return
        self.api.get_me()
        try:
            self.api.set_my_commands(
                [
                    {"command": "status", "description": "Sistem durumu ve pencere bilgisi"},
                    {"command": "run", "description": "Claude çalıştır (onay ister)"},
                    {"command": "usage", "description": "Claude kullanım bilgisini getir"},
                    {"command": "sync_usage", "description": "Kullanımı ölç ve planı güncelle"},
                    {"command": "schedule", "description": "Sonraki çalışma zamanları"},
                    {"command": "workhours", "description": "Yoğun çalışma saatlerini ayarla"},
                    {"command": "last", "description": "Son çalışma detayı"},
                    {"command": "health", "description": "Sağlık kontrolü"},
                    {"command": "logs", "description": "Son kayıtlar"},
                    {"command": "ping", "description": "Bot canlılık kontrolü"},
                    {"command": "automation_on", "description": "Otomasyonu etkinleştir"},
                    {"command": "automation_off", "description": "Otomasyonu devre dışı bırak"},
                    {"command": "sleep_on", "description": "Uyku engellemeyi aç"},
                    {"command": "sleep_off", "description": "Uyku engellemeyi kapat"},
                    {"command": "calibrate_5h", "description": "5 saatlik pencereyi kalibre et"},
                    {"command": "calibrate_weekly", "description": "Haftalık pencereyi kalibre et"},
                    {"command": "users", "description": "Yetkili kullanıcıları listele"},
                    {
                        "command": "setmodel",
                        "description": "Model değiştir (auto/haiku/sonnet/opus)",
                    },
                    {"command": "help", "description": "Komut listesi"},
                ]
            )
            self.api.set_my_description(
                "Claude Code abonelik isteklerinizi 5 saatlik kullanım pencerelerinde "
                "otomatik olarak yöneten macOS otomasyon botu."
            )
            self.api.set_my_short_description("Claude Code pencere zamanlayıcı ve otomasyon botu")
        except Exception as exc:
            log_event(
                self.paths,
                {
                    "status": "telegram_menu_update_failed",
                    "sanitized_error": str(exc)[:200],
                },
            )
        with FileLock(self.paths.bot_lock, timeout=0, error_code=ErrorCode.ALREADY_RUNNING):
            while True:
                if not self._supervisor_alive():
                    log_event(self.paths, {"status": "telegram_supervisor_gone"})
                    return
                offset = int(load_state(self.paths).get("telegram_offset", 0))
                try:
                    self._drain_notifications()
                    supervisor_gone = False
                    try:
                        updates = self.api.get_updates(offset, timeout=10)
                    finally:
                        supervisor_gone = not self._supervisor_alive()
                    if supervisor_gone:
                        log_event(self.paths, {"status": "telegram_supervisor_gone"})
                        return
                    for update in updates:
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
                    if not self._wait_for_retry(5):
                        return
                except Exception as exc:
                    log_event(
                        self.paths,
                        {
                            "status": "telegram_unexpected_error",
                            "sanitized_error": str(exc)[:200],
                        },
                    )
                    if not self._wait_for_retry(5):
                        return

    def _supervisor_alive(self) -> bool:
        if self.supervisor_pid is None:
            return True
        if self.supervisor_pid <= 1 or os.getppid() != self.supervisor_pid:
            return False
        try:
            os.kill(self.supervisor_pid, 0)
        except (ProcessLookupError, PermissionError):
            return False
        return True

    def _wait_for_retry(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not self._supervisor_alive():
                return False
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        return self._supervisor_alive()

    def _cmd_status(self, state: dict[str, Any]) -> str:
        """Build a rich /status response with sections and countdown."""
        from .windows import format_countdown

        enabled = "✅ Açık" if self.config["enabled"] else "❌ Kapalı"
        bg = "✅ Açık" if self.config["background_enabled"] else "❌ Kapalı"
        tz = self.config["timezone"]
        model = self.config.get("model", "auto")
        health = health_report(self.paths)
        health_str = "✅ Sağlıklı" if health.get("ok", False) else "⚠️ Sorun var"
        now_utc = datetime.now(timezone.utc)

        # Build windows section
        next_windows = next_runs(self.paths, self.config)
        window_lines: list[str] = []
        for wtype, dt in next_windows.items():
            label = "5 saatlik" if wtype == "five_hour" else "Haftalık"
            countdown = format_countdown(dt, now_utc)
            window_lines.append(f"  • {label}: {_fmt_dt(dt, tz)} ({countdown})")
        windows_str = "\n".join(window_lines) if window_lines else "  Pencere tanımlı değil"

        # Build last run section
        last = state.get("last_run")
        last_section = ""
        if isinstance(last, dict):
            icon = "✅" if last.get("status") == "success" else "❌"
            time_str = _fmt_dt(last.get("trigger_time"), tz)
            last_model = last.get("selected_model", "?")
            last_section = (
                f"\n\n🕐 *Son Çalışma*\n"
                f"  {icon} {_md_escape(time_str)}\n"
                f"  Model: {_md_escape(str(last_model))}"
            )

        return (
            f"📊 *Sistem Durumu*\n\n"
            f"Otomasyon: {enabled}\n"
            f"Uyku önleme: {bg}\n"
            f"Model: *{_md_escape(str(model))}*\n"
            f"Zaman dilimi: {_md_escape(tz)}\n"
            f"Sağlık: {health_str}\n\n"
            f"📅 *Sonraki Çalışmalar*\n{windows_str}"
            f"{last_section}"
        )

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


def _usage_error_message(error: AppError) -> str:
    messages = {
        ErrorCode.ALREADY_RUNNING: "Başka bir Claude işlemi çalışıyor. Biraz sonra tekrar deneyin.",
        ErrorCode.CLAUDE_NOT_AUTHENTICATED: (
            "Claude abonelik oturumu açık değil. Mac'te bir kez claude auth login çalıştırın."
        ),
        ErrorCode.TIMEOUT: "Claude kullanım sorgusu zaman aşımına uğradı. Tekrar deneyin.",
        ErrorCode.CLAUDE_USAGE_UNAVAILABLE: (
            "Claude kullanım bilgisi alınamadı. Claude Code sürümünü ve oturumu kontrol edin."
        ),
        ErrorCode.API_KEY_DETECTED: (
            "API/provider ayarı algılandı; abonelik kullanım sorgusu güvenlik için durduruldu."
        ),
        ErrorCode.CLAUDE_NOT_FOUND: "Claude Code bulunamadı.",
    }
    return messages.get(error.code, "Claude kullanım bilgisi alınamadı. Tekrar deneyin.")


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


def notify(paths: AppPaths, text: str) -> None:
    config = load_config(paths, create=True)["telegram"]
    target = config.get("notification_channel_id") or config.get("notification_chat_id")
    if not config["enabled"] or type(target) is not int:
        return
    update_state(
        paths,
        lambda state: state.setdefault("notification_queue", []).append(text[:3900]),
    )
