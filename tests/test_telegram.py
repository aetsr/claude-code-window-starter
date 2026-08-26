from __future__ import annotations

import io
import json
import ssl
import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any
from unittest import mock

from claude_starter.config import DEFAULT_CONFIG, load_config, save_config
from claude_starter.errors import AppError, ErrorCode
from claude_starter.paths import AppPaths
from claude_starter.state import load_state
from claude_starter.telegram_api import TelegramAPI, split_message
from claude_starter.telegram_bot import TelegramBot


class FakeAPI:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, dict[str, Any] | None]] = []
        self.callbacks: list[tuple[str, str]] = []
        self.actions: list[tuple[int, str]] = []
        self.events: list[str] = []
        self.message_options: list[dict[str, Any]] = []

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = None,
        auto_parse_mode: bool = True,
    ) -> None:
        self.events.append("message")
        self.messages.append((chat_id, text, reply_markup))
        self.message_options.append({"parse_mode": parse_mode, "auto_parse_mode": auto_parse_mode})

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        self.events.append("typing")
        self.actions.append((chat_id, action))

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
        self.assertEqual(self.api.messages[-1][1], "Bu komut için yetkiniz yok.")
        self.assertEqual(self.api.actions, [])

    def test_usage_cooldown_stops_before_typing_and_query(self) -> None:
        with (
            mock.patch.object(self.bot, "_rate_allowed", return_value=False),
            mock.patch("claude_starter.telegram_bot.query_usage") as query,
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
        query.assert_not_called()
        self.assertEqual(self.api.actions, [])

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
            "claude_starter.telegram_bot.query_usage",
            return_value={
                "formatted_text": (
                    "📊 Claude Kullanım Bilgisi\n• Current session [all] 40% used\n• Resets in 2h"
                )
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
        self.assertEqual(self.api.actions, [(100, "typing")])
        self.assertEqual(self.api.events, ["typing", "message"])
        self.assertFalse(self.api.message_options[-1]["auto_parse_mode"])

    def test_workhours_enables_adaptive_plan(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "from": {"id": 100},
                    "chat": {"id": 100, "type": "private"},
                    "text": "/workhours 09:00 18:00",
                }
            }
        )
        config = load_config(self.paths)
        self.assertEqual(config["windows"]["five_hour"]["mode"], "adaptive")
        self.assertEqual(config["windows"]["five_hour"]["busy_start_local"], "09:00")
        self.assertIn("Hafta içi / Maksimum kota", self.api.messages[-1][1])

    def test_workhours_rejects_overnight_period(self) -> None:
        self.bot.handle_update(
            {
                "message": {
                    "from": {"id": 100},
                    "chat": {"id": 100, "type": "private"},
                    "text": "/workhours 22:00 06:00",
                }
            }
        )
        self.assertIn("gece yarısını geçen", self.api.messages[-1][1])

    def test_sync_usage_returns_plan_confidence(self) -> None:
        with mock.patch(
            "claude_starter.telegram_bot.query_usage",
            return_value={"formatted_text": "Kullanım senkronize edildi."},
        ):
            self.bot.handle_update(
                {
                    "message": {
                        "from": {"id": 100},
                        "chat": {"id": 100, "type": "private"},
                        "text": "/sync_usage",
                    }
                }
            )
        self.assertIn("Plan güveni", self.api.messages[-1][1])
        self.assertEqual(self.api.actions, [(100, "typing")])

    def test_usage_errors_are_short_turkish_plain_text(self) -> None:
        errors = (
            (
                AppError(ErrorCode.ALREADY_RUNNING),
                "Başka bir Claude işlemi çalışıyor",
            ),
            (
                AppError(ErrorCode.CLAUDE_NOT_AUTHENTICATED),
                "Claude abonelik oturumu açık değil",
            ),
            (AppError(ErrorCode.TIMEOUT), "zaman aşımına uğradı"),
            (
                AppError(ErrorCode.CLAUDE_USAGE_UNAVAILABLE),
                "Claude kullanım bilgisi alınamadı",
            ),
        )
        for error, expected in errors:
            with self.subTest(code=error.code):
                self.api = FakeAPI()
                self.bot = TelegramBot(self.paths, self.api)  # type: ignore[arg-type]
                with (
                    mock.patch(
                        "claude_starter.telegram_bot.query_usage",
                        side_effect=error,
                    ),
                    mock.patch.object(self.bot, "_rate_allowed", return_value=True),
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
                self.assertIn(expected, self.api.messages[-1][1])
                self.assertFalse(self.api.message_options[-1]["auto_parse_mode"])

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
        self.assertNotEqual(first_text, "Lütfen birkaç saniye sonra tekrar deneyin.")
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
        self.assertEqual(second_text, "Lütfen birkaç saniye sonra tekrar deneyin.")

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

    def test_worker_exits_after_poll_when_supervisor_is_gone(self) -> None:
        class PollingAPI(FakeAPI):
            def __init__(self) -> None:
                super().__init__()
                self.poll_timeouts: list[int] = []

            def get_me(self) -> dict[str, Any]:
                return {"id": 1}

            def set_my_commands(self, commands: list[dict[str, str]]) -> None:
                del commands

            def get_updates(self, offset: int, timeout: int = 10) -> list[dict[str, Any]]:
                del offset
                self.poll_timeouts.append(timeout)
                return []

        api = PollingAPI()
        bot = TelegramBot(
            self.paths,
            api,  # type: ignore[arg-type]
            supervisor_pid=1234,
        )
        with mock.patch.object(
            bot,
            "_supervisor_alive",
            side_effect=[True, True, False],
        ):
            bot.run_forever()
        self.assertEqual(api.poll_timeouts, [10])

        from claude_starter.locks import FileLock

        with FileLock(self.paths.bot_lock, timeout=0):
            pass

    def test_update_offset_advances_only_after_handler_completes(self) -> None:
        class OneUpdateAPI(FakeAPI):
            def get_me(self) -> dict[str, Any]:
                return {"id": 1}

            def set_my_commands(self, commands: list[dict[str, str]]) -> None:
                del commands

            def get_updates(self, offset: int, timeout: int = 10) -> list[dict[str, Any]]:
                del offset, timeout
                return [{"update_id": 9}]

        api = OneUpdateAPI()
        bot = TelegramBot(self.paths, api)  # type: ignore[arg-type]
        with (
            mock.patch.object(
                bot,
                "_supervisor_alive",
                side_effect=[True, True, True],
            ),
            mock.patch.object(
                bot,
                "handle_update",
                side_effect=AppError(ErrorCode.TIMEOUT),
            ),
            mock.patch.object(bot, "_wait_for_retry", return_value=False),
        ):
            bot.run_forever()
        self.assertEqual(load_state(self.paths).get("telegram_offset", 0), 0)

    def test_update_offset_advances_after_handler_completes(self) -> None:
        class OneUpdateAPI(FakeAPI):
            def get_me(self) -> dict[str, Any]:
                return {"id": 1}

            def set_my_commands(self, commands: list[dict[str, str]]) -> None:
                del commands

            def get_updates(self, offset: int, timeout: int = 10) -> list[dict[str, Any]]:
                del offset, timeout
                return [{"update_id": 9}]

        api = OneUpdateAPI()
        bot = TelegramBot(self.paths, api)  # type: ignore[arg-type]
        with (
            mock.patch.object(
                bot,
                "_supervisor_alive",
                side_effect=[True, True, True, False],
            ),
            mock.patch.object(bot, "handle_update") as handle,
        ):
            bot.run_forever()
        handle.assert_called_once_with({"update_id": 9})
        self.assertEqual(load_state(self.paths).get("telegram_offset"), 10)

    def test_supervisor_pid_must_match_actual_parent(self) -> None:
        bot = TelegramBot(
            self.paths,
            self.api,  # type: ignore[arg-type]
            supervisor_pid=4321,
        )
        with mock.patch("claude_starter.telegram_bot.os.getppid", return_value=1234):
            self.assertFalse(bot._supervisor_alive())
        with (
            mock.patch("claude_starter.telegram_bot.os.getppid", return_value=4321),
            mock.patch("claude_starter.telegram_bot.os.kill") as kill,
        ):
            self.assertTrue(bot._supervisor_alive())
        kill.assert_called_once_with(4321, 0)


class TelegramAPITests(unittest.TestCase):
    def _api(self) -> TelegramAPI:
        return TelegramAPI(
            "test-token",
            ssl_context=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
        )

    def test_http_400_body_description_is_preserved_safely(self) -> None:
        body = io.BytesIO(
            json.dumps(
                {
                    "ok": False,
                    "description": "Bad Request: can't parse entities",
                }
            ).encode()
        )
        error = urllib.error.HTTPError(
            "https://api.telegram.org/",
            400,
            "Bad Request",
            {},
            body,
        )
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(AppError) as context:
                self._api().call("sendMessage", {"chat_id": 1, "text": "bad"})
        self.assertEqual(context.exception.code, ErrorCode.TELEGRAM_API_ERROR)
        self.assertEqual(context.exception.details["http_status"], 400)
        self.assertIn("can't parse entities", context.exception.message)

    def test_markdown_entity_400_retries_once_as_plain_text(self) -> None:
        api = self._api()
        payloads: list[dict[str, Any]] = []

        def call(method: str, payload: dict[str, Any]) -> None:
            self.assertEqual(method, "sendMessage")
            payloads.append(dict(payload))
            if len(payloads) == 1:
                raise AppError(
                    ErrorCode.TELEGRAM_API_ERROR,
                    "Telegram HTTP 400: can't parse entities",
                    {
                        "http_status": 400,
                        "description": "Bad Request: can't parse entities",
                    },
                )

        with mock.patch.object(api, "call", side_effect=call):
            api.send_message(1, "📊 *Usage [all]*")
        self.assertEqual(len(payloads), 2)
        self.assertEqual(payloads[0]["parse_mode"], "Markdown")
        self.assertNotIn("parse_mode", payloads[1])
        self.assertEqual(payloads[1]["text"], payloads[0]["text"])

    def test_usage_special_characters_are_sent_without_parse_mode(self) -> None:
        api = self._api()
        payloads: list[dict[str, Any]] = []

        def call(method: str, payload: dict[str, Any]) -> None:
            self.assertEqual(method, "sendMessage")
            payloads.append(dict(payload))

        with mock.patch.object(api, "call", side_effect=call):
            api.send_message(
                1,
                "Current session: 40% [all] * literal _ text",
                auto_parse_mode=False,
            )
        self.assertEqual(len(payloads), 1)
        self.assertNotIn("parse_mode", payloads[0])

    def test_long_poll_uses_short_bounded_http_timeout(self) -> None:
        api = self._api()
        with mock.patch.object(api, "call", return_value=[]) as call:
            api.get_updates(7, timeout=10)
        self.assertEqual(call.call_args.kwargs["request_timeout"], 30)

    def test_long_poll_socket_timeout_is_an_empty_poll(self) -> None:
        api = self._api()
        error = AppError(
            ErrorCode.TELEGRAM_API_ERROR,
            "Telegram network request timed out",
            {"timeout": True},
        )
        with mock.patch.object(api, "call", side_effect=error):
            self.assertEqual(api.get_updates(7, timeout=10), [])

    def test_call_classifies_raw_read_timeout(self) -> None:
        with mock.patch("urllib.request.urlopen", side_effect=TimeoutError("read timed out")):
            with self.assertRaises(AppError) as context:
                self._api().call("getMe")
        self.assertEqual(context.exception.code, ErrorCode.TELEGRAM_API_ERROR)
        self.assertTrue(context.exception.details["timeout"])

    def test_long_poll_timeout_does_not_trigger_backoff(self) -> None:
        """A long-poll timeout must return [] without raising, so the bot loop
        immediately opens the next poll instead of entering a 5-second backoff."""
        api = self._api()
        timeout_error = AppError(
            ErrorCode.TELEGRAM_API_ERROR,
            "Telegram network request timed out",
            {"timeout": True},
        )
        with mock.patch.object(api, "call", side_effect=timeout_error):
            result = api.get_updates(0, timeout=10)
        self.assertEqual(result, [])

    def test_non_timeout_api_error_still_raises(self) -> None:
        """Only timeout errors should be swallowed by get_updates; other API
        errors must propagate so the bot can log and handle them."""
        api = self._api()
        network_error = AppError(
            ErrorCode.TELEGRAM_API_ERROR,
            "Telegram network request failed",
            {"timeout": False},
        )
        with mock.patch.object(api, "call", side_effect=network_error):
            with self.assertRaises(AppError):
                api.get_updates(0, timeout=10)


if __name__ == "__main__":
    unittest.main()
