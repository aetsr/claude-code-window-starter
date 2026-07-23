from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from claude_starter.config import DEFAULT_CONFIG, save_config
from claude_starter.paths import AppPaths
from claude_starter.telegram_api import split_message
from claude_starter.telegram_bot import TelegramBot


class FakeAPI:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict[str, Any] | None]] = []
        self.callbacks: list[tuple[str, str]] = []

    def send_message(self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None) -> None:
        self.messages.append((chat_id, text, reply_markup))

    def answer_callback(self, callback_id: str, text: str) -> None:
        self.callbacks.append((callback_id, text))


class TelegramTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temporary.name))
        self.paths.ensure()
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        config["telegram"].update(
            {"enabled": True, "allowed_user_ids": [100], "allowed_chat_ids": [100], "command_cooldown_seconds": 0}
        )
        save_config(self.paths, config)
        self.api = FakeAPI()
        self.bot = TelegramBot(self.paths, self.api)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_allowlist_requires_numeric_user_and_chat(self) -> None:
        self.assertTrue(self.bot.authorized(100, 100, "private"))
        self.assertFalse(self.bot.authorized(101, 100, "private"))
        self.assertFalse(self.bot.authorized(100, -200, "group"))

    def test_unauthorized_response_reveals_nothing(self) -> None:
        self.bot.handle_update({"message": {"from": {"id": 999}, "chat": {"id": 999, "type": "private"}, "text": "/status"}})
        self.assertEqual(self.api.messages[-1][1], "Unauthorized")

    def test_setprompt_requires_owner_bound_confirmation(self) -> None:
        self.bot.handle_update({"message": {"from": {"id": 100}, "chat": {"id": 100, "type": "private"}, "text": "/setprompt Respond safely"}})
        markup = self.api.messages[-1][2]
        self.assertIsNotNone(markup)
        callback_data = markup["inline_keyboard"][0][0]["callback_data"]  # type: ignore[index]
        self.bot.handle_update({"callback_query": {"id": "cb", "from": {"id": 101}, "message": {"chat": {"id": 100, "type": "private"}}, "data": callback_data}})
        self.assertEqual(self.api.callbacks[-1][1], "Unauthorized")

    def test_long_messages_are_split_under_limit(self) -> None:
        chunks = split_message("x" * 8001)
        self.assertEqual("".join(chunks), "x" * 8001)
        self.assertTrue(all(len(chunk) <= 3900 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
