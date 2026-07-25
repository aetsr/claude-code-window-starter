from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .errors import AppError, ErrorCode
from .macos_trust import trusted_ssl_context


class TelegramAPI:
    def __init__(
        self,
        token: str,
        *,
        timeout: int = 60,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._token = token
        self._timeout = timeout
        self._base = f"https://api.telegram.org/bot{token}/"
        self._ssl_context = ssl_context or trusted_ssl_context()

    def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        encoded = urllib.parse.urlencode(_encode_payload(payload or {})).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310
            self._base + method,
            data=encoded,
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310  # nosec B310
                request,
                timeout=self._timeout,
                context=self._ssl_context,
            ) as response:
                body = response.read(2 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            raise AppError(ErrorCode.TELEGRAM_API_ERROR, f"Telegram HTTP error {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise AppError(
                ErrorCode.TELEGRAM_API_ERROR, "Telegram network request failed"
            ) from exc
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

    def get_updates(self, offset: int, timeout: int = 50) -> list[dict[str, Any]]:
        result = self.call(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["message", "callback_query"],
            },
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
    ) -> None:
        chunks = split_message(text)
        for index, chunk in enumerate(chunks):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if reply_markup is not None and index == len(chunks) - 1:
                payload["reply_markup"] = reply_markup
            self.call("sendMessage", payload)

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:200]})


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
