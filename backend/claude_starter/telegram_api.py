from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .errors import AppError, ErrorCode
from .logging_utils import sanitize_text
from .macos_trust import trusted_ssl_context


class TelegramAPI:
    def __init__(
        self,
        token: str,
        *,
        timeout: int = 15,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._token = token
        self._timeout = timeout
        self._base = f"https://api.telegram.org/bot{token}/"
        self._ssl_context = ssl_context or trusted_ssl_context()

    def call(
        self,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        request_timeout: int | None = None,
    ) -> Any:
        encoded = urllib.parse.urlencode(_encode_payload(payload or {})).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310
            self._base + method,
            data=encoded,
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310  # nosec B310
                request,
                timeout=request_timeout or self._timeout,
                context=self._ssl_context,
            ) as response:
                body = response.read(2 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            try:
                error_body = exc.read(4096)
            except (AttributeError, OSError, ValueError):
                error_body = b""
            description = _telegram_error_description(error_body)
            message = f"Telegram HTTP {exc.code}: {description}"
            raise AppError(
                ErrorCode.TELEGRAM_API_ERROR,
                sanitize_text(message, 300),
                {
                    "http_status": exc.code,
                    "description": sanitize_text(description, 200),
                },
            ) from exc
        except urllib.error.URLError as exc:
            raise AppError(ErrorCode.TELEGRAM_API_ERROR, "Telegram network request failed") from exc
        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise AppError(ErrorCode.TELEGRAM_API_ERROR, "Telegram returned invalid JSON") from exc
        if not isinstance(result, dict) or not result.get("ok"):
            description = (
                result.get("description", "Telegram API error")
                if isinstance(result, dict)
                else "Telegram API error"
            )
            raise AppError(ErrorCode.TELEGRAM_API_ERROR, str(description)[:200])
        return result.get("result")

    def get_me(self) -> dict[str, Any]:
        result = self.call("getMe")
        return result if isinstance(result, dict) else {}

    def get_updates(self, offset: int, timeout: int = 10) -> list[dict[str, Any]]:
        result = self.call(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["message", "callback_query"],
            },
            request_timeout=max(5, timeout + 5),
        )
        return (
            [item for item in result if isinstance(item, dict)] if isinstance(result, list) else []
        )

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
        auto_parse_mode: bool = True,
    ) -> None:
        if auto_parse_mode and parse_mode is None and "*" in text:
            parse_mode = "Markdown"
        chunks = split_message(text)
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            if reply_markup is not None and index == len(chunks) - 1:
                payload["reply_markup"] = reply_markup
            try:
                self.call("sendMessage", payload)
            except AppError as exc:
                if not parse_mode or not _is_entity_format_error(exc):
                    raise
                payload.pop("parse_mode", None)
                self.call("sendMessage", payload)

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self.call("sendChatAction", {"chat_id": chat_id, "action": action})

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            self.call("editMessageText", payload)
        except AppError:
            pass

    def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        self.call("setMyCommands", {"commands": commands})

    def set_my_description(self, description: str) -> None:
        self.call("setMyDescription", {"description": description[:512]})

    def set_my_short_description(self, short_description: str) -> None:
        self.call("setMyShortDescription", {"short_description": short_description[:120]})


def _encode_payload(payload: dict[str, Any]) -> dict[str, str | int]:
    result: dict[str, str | int] = {}
    for key, value in payload.items():
        if isinstance(value, dict | list):
            result[key] = json.dumps(value, separators=(",", ":"))
        elif isinstance(value, bool):
            result[key] = "true" if value else "false"
        elif value is not None:
            result[key] = value
    return result


def _telegram_error_description(body: bytes) -> str:
    try:
        value = json.loads(body.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        value = None
    if isinstance(value, dict) and isinstance(value.get("description"), str):
        return value["description"][:200]
    return "Telegram API error"


def _is_entity_format_error(error: AppError) -> bool:
    if error.code != ErrorCode.TELEGRAM_API_ERROR:
        return False
    details = error.details or {}
    if details.get("http_status") != 400:
        return False
    description = str(details.get("description", error.message)).lower()
    return any(
        marker in description
        for marker in (
            "parse entities",
            "can't parse entities",
            "cant parse entities",
            "entity",
            "can't find end",
        )
    )


def split_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks
