from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from claude_starter.config import DEFAULT_CONFIG, save_config
from claude_starter.paths import AppPaths
from claude_starter.telegram_api import split_message
from claude_starter.telegram_bot import TelegramBot


class FakeAPI:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict[str, Any] | None]] = []
        self.callbacks: list[tuple[str, str]] = []

    def send_message(
        self, chat_id: int, text: str, *, reply_markup: dict[str, Any] | None = None
    ) -> None:
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
            {
                "enabled": True,
                "allowed_user_ids": [100],
                "allowed_chat_ids": [100],
                "command_cooldown_seconds": 1,
            }
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
        self.bot.handle_update(
            {
                "message": {
                    "from": {"id": 999},
                    "chat": {"id": 999, "type": "private"},
                    "text": "/status",
                }
            }
        )
        self.assertEqual(self.api.messages[-1][1], "Unauthorized")

    def test_setprompt_requires_owner_bound_confirmation(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "from": {"id": 100},
                    "chat": {"id": 100, "type": "private"},
                    "text": "/setprompt Respond safely",
                }
            }
        )
        markup = self.api.messages[-1][2]
        self.assertIsNotNone(markup)
        callback_data = markup["inline_keyboard"][0][0]["callback_data"]  # type: ignore[index]
        self.bot.handle_update(
            {
                "callback_query": {
                    "id": "cb",
                    "from": {"id": 101},
                    "message": {"chat": {"id": 100, "type": "private"}},
                    "data": callback_data,
                }
            }
        )
        self.assertEqual(self.api.callbacks[-1][1], "Unauthorized")

    def test_long_messages_are_split_under_limit(self) -> None:
        chunks = split_message("x" * 8001)
        self.assertEqual("".join(chunks), "x" * 8001)
        self.assertTrue(all(len(chunk) <= 3900 for chunk in chunks))

    def test_usage_returns_formatted_usage_message(self) -> None:
        with mock.patch(
            "claude_starter.telegram_bot.query_active_session_usage",
            return_value={
                "formatted_text": "📊 *Claude Kullanım Bilgisi*\n• 5h remaining 40%\n• Reset in 2h"
            },
        ):
            self.bot.handle_update(
                {
                    "message": {
                        "from": {"id": 100},
                        "chat": {"id": 100, "type": "private"},
                        "text": "/usage",
                    }
                }
            )
        self.assertIn("Claude Kullanım Bilgisi", self.api.messages[-1][1])

    def test_confirm_callback_executes_for_owner(self) -> None:
        """The confirmation owner should be able to confirm and get an action response."""
        self.bot.handle_update(
            {
                "message": {
                    "from": {"id": 100},
                    "chat": {"id": 100, "type": "private"},
                    "text": "/setprompt New prompt text",
                }
            }
        )
        markup = self.api.messages[-1][2]
        self.assertIsNotNone(markup)
        callback_data = markup["inline_keyboard"][0][0]["callback_data"]  # type: ignore[index]
        # Owner (same user_id + chat_id) confirms
        self.bot.handle_update(
            {
                "callback_query": {
                    "id": "cb_owner",
                    "from": {"id": 100},
                    "message": {"chat": {"id": 100, "type": "private"}},
                    "data": callback_data,
                }
            }
        )
        self.assertIn(self.api.callbacks[-1][1], ("Updated", "✅ Güncellendi"))

    def test_callback_cancel_clears_confirmation(self) -> None:
        """Cancelling a confirmation should respond with 'Cancelled'."""
        self.bot.handle_update(
            {
                "message": {
                    "from": {"id": 100},
                    "chat": {"id": 100, "type": "private"},
                    "text": "/setprompt Will be cancelled",
                }
            }
        )
        markup = self.api.messages[-1][2]
        self.assertIsNotNone(markup)
        cancel_data = markup["inline_keyboard"][0][1]["callback_data"]  # type: ignore[index]
        self.bot.handle_update(
            {
                "callback_query": {
                    "id": "cb_cancel",
                    "from": {"id": 100},
                    "message": {"chat": {"id": 100, "type": "private"}},
                    "data": cancel_data,
                }
            }
        )
        self.assertIn(self.api.callbacks[-1][1], ("Cancelled", "❌ İptal edildi"))

    def test_malformed_confirmation_expiry_is_treated_as_expired(self) -> None:
        from claude_starter.state import update_state

        update_state(
            self.paths,
            lambda state: state.setdefault("telegram_confirmations", {}).__setitem__(
                "nonce-bad-expiry",
                {
                    "user_id": 100,
                    "chat_id": 100,
                    "action": "run",
                    "expires": "not-a-number",
                },
            ),
        )
        self.bot.handle_update(
            {
                "callback_query": {
                    "id": "cb_bad_expiry",
                    "from": {"id": 100},
                    "message": {"chat": {"id": 100, "type": "private"}},
                    "data": "confirm:nonce-bad-expiry",
                }
            }
        )
        self.assertIn(self.api.callbacks[-1][1], ("Expired", "⏱ Süre doldu"))

    def test_commands_are_rate_limited_within_cooldown(self) -> None:
        """A second command sent within the cooldown window must be rejected."""
        # First /status is allowed and records the rate-limit timestamp
        self.bot.handle_update(
            {
                "message": {
                    "from": {"id": 100},
                    "chat": {"id": 100, "type": "private"},
                    "text": "/status",
                }
            }
        )
        first_text = self.api.messages[-1][1]
        self.assertNotEqual(first_text, "Rate limited; try again shortly.")
        # Second /status is sent immediately (well within the 1-second cooldown)
        self.bot.handle_update(
            {
                "message": {
                    "from": {"id": 100},
                    "chat": {"id": 100, "type": "private"},
                    "text": "/status",
                }
            }
        )
        second_text = self.api.messages[-1][1]
        self.assertEqual(second_text, "Rate limited; try again shortly.")

    def test_drain_notifications_preserves_concurrent_appends(self) -> None:
        """Items added to the queue while draining must not be lost."""
        from claude_starter.state import update_state

        config = json.loads(json.dumps(self.bot.config))
        config["telegram"]["notification_chat_id"] = 100
        from claude_starter.config import save_config

        save_config(self.paths, config)
        # Re-create bot so it picks up new config
        self.bot = type(self.bot)(self.paths, self.api)
        # Pre-populate the queue with 11 items
        for i in range(11):
            update_state(
                self.paths,
                lambda s, msg=f"msg{i}": s.setdefault("notification_queue", []).append(msg),
            )
        # Drain processes first 10
        self.bot._drain_notifications()
        from claude_starter.state import load_state

        remaining = load_state(self.paths).get("notification_queue", [])
        # Exactly the 11th item should survive
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0], "msg10")
        # The 10 items were sent
        self.assertEqual(len(self.api.messages), 10)


if __name__ == "__main__":
    unittest.main()
