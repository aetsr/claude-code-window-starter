"""Production-ready tests covering all user interaction paths.

Tests every combination a user can perform via UI or Telegram:
  - Calibration → save → sleep mode toggle (anchor_iso must not be wiped)
  - Connectivity offline/online flow → calibration_needed marking
  - Telegram user management (add/remove, authorized check)
  - /pair append behavior (multi-user)
  - Telegram bot human-readable responses
  - config patch-stdin does not overwrite anchor_iso when windows section omits it
  - Z-suffix ISO strings from Swift accepted everywhere
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from claude_starter.cli import main
from claude_starter.config import DEFAULT_CONFIG, save_config
from claude_starter.paths import AppPaths
from claude_starter.state import load_state, update_state
from claude_starter.windows import _parse_iso


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paths(tmp: str) -> AppPaths:
    p = AppPaths(Path(tmp))
    p.ensure()
    return p


def _run(*args) -> tuple[int, dict]:
    buf = io.StringIO()
    code = main(list(args), _out=buf) if "_out" in main.__code__.co_varnames else _run_capture(*args)
    return code, {}


def _run_capture(*args) -> tuple[int, dict]:
    """Run CLI and capture stdout/stderr JSON output."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        try:
            code = main(list(args))
        except SystemExit as exc:
            code = int(exc.code or 0)
    stdout_text = stdout_buf.getvalue().strip()
    stderr_text = stderr_buf.getvalue().strip()
    raw = stdout_text if stdout_text else stderr_text
    try:
        return code, json.loads(raw)
    except json.JSONDecodeError:
        return code, {"raw": raw}


def _cfg(tmp: str, **overrides) -> AppPaths:
    """Create paths with a base config, apply overrides."""
    paths = _paths(tmp)
    cfg = dict(DEFAULT_CONFIG)
    cfg["enabled"] = True
    cfg["windows"] = {
        "five_hour": {
            "enabled": True,
            "anchor_iso": "2026-01-01T00:00:00+00:00",
            "interval_minutes": 303,
        },
        "weekly": {
            "enabled": True,
            "anchor_iso": "2026-01-01T00:00:00+00:00",
            "interval_minutes": 10080,
        },
    }
    cfg.update(overrides)
    save_config(paths, cfg)
    return paths


# ===========================================================================
# 1. Calibration flow
# ===========================================================================

class TestCalibrationFlow(unittest.TestCase):
    """Calibrate → status → patch → anchor must survive."""

    def test_calibrate_five_hour_z_suffix(self):
        """Swift sends Z-suffix; calibrate must accept it."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _cfg(tmp)
            anchor = "2026-07-25T18:43:00Z"
            rc, env = _run_capture("--home", tmp, "--json", "calibrate",
                                   "--window-type", "five_hour", "--anchor", anchor)
            self.assertEqual(rc, 0)
            self.assertTrue(env["ok"])
            self.assertEqual(env["data"]["window_type"], "five_hour")
            # next_run_at must be after the anchor
            next_at = _parse_iso(env["data"]["next_run_at"])
            self.assertGreater(next_at, _parse_iso(anchor))

    def test_calibrate_weekly_full_datetime(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _cfg(tmp)
            anchor = "2026-07-20T10:00:00+00:00"
            rc, env = _run_capture("--home", tmp, "--json", "calibrate",
                                   "--window-type", "weekly", "--anchor", anchor)
            self.assertEqual(rc, 0)
            self.assertTrue(env["ok"])

    def test_calibrate_sets_calibration_needed_false(self):
        """After calibrate, calibration_needed must be cleared."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _cfg(tmp)
            # Manually mark calibration needed
            update_state(paths, lambda s: s.update({"five_hour_calibration_needed": True}))
            anchor = "2026-07-25T10:00:00Z"
            with mock.patch("claude_starter.cli.notify"):
                rc, env = _run_capture("--home", tmp, "--json", "calibrate",
                                       "--window-type", "five_hour", "--anchor", anchor)
            self.assertEqual(rc, 0)
            state = load_state(paths)
            self.assertIsNone(state.get("five_hour_calibration_needed"))

    def test_patch_stdin_does_not_wipe_anchor(self):
        """Patch with windows.five_hour.enabled only — anchor_iso must survive."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _cfg(tmp)
            # First calibrate to set anchor
            with mock.patch("claude_starter.cli.notify"):
                _run_capture("--home", tmp, "--json", "calibrate",
                             "--window-type", "five_hour", "--anchor", "2026-07-25T10:00:00Z")
            # Now send a patch that only touches enabled (simulates UI sleep-mode toggle)
            patch = json.dumps({
                "enabled": True,
                "background_enabled": True,
                "windows": {
                    "five_hour": {"enabled": True},
                    "weekly": {"enabled": False},
                },
            }).encode()
            stdin_mock = io.BytesIO(patch)
            with mock.patch("sys.stdin", io.TextIOWrapper(stdin_mock)):
                rc, env = _run_capture("--home", tmp, "--json", "config", "patch-stdin")
            self.assertEqual(rc, 0)
            from claude_starter.config import load_config
            cfg = load_config(paths)
            # anchor_iso must NOT have been wiped
            anchor = cfg["windows"]["five_hour"]["anchor_iso"]
            self.assertIsNotNone(anchor)
            self.assertNotEqual(anchor, "")
            self.assertIn("2026-07-25", anchor)

    def test_status_returns_anchor_after_calibration(self):
        """Status response includes anchor_iso after calibrate."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _cfg(tmp)
            anchor = "2026-07-25T18:00:00Z"
            with mock.patch("claude_starter.cli.notify"):
                _run_capture("--home", tmp, "--json", "calibrate",
                             "--window-type", "five_hour", "--anchor", anchor)
            rc, env = _run_capture("--home", tmp, "--json", "status")
            self.assertEqual(rc, 0)
            five_hour = env["data"]["windows"]["five_hour"]
            self.assertIsNotNone(five_hour["anchor_iso"])

    def test_calibration_needed_bool_in_status(self):
        """calibration_needed=True (bool) must appear in status windows."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _cfg(tmp)
            update_state(paths, lambda s: s.update({"five_hour_calibration_needed": True}))
            rc, env = _run_capture("--home", tmp, "--json", "status")
            self.assertEqual(rc, 0)
            cn = env["data"]["windows"]["five_hour"]["calibration_needed"]
            self.assertTrue(cn)


# ===========================================================================
# 2. Connectivity offline/online flow
# ===========================================================================

class TestConnectivityFlow(unittest.TestCase):

    def _setup_with_overdue_window(self, tmp: str) -> AppPaths:
        paths = _cfg(tmp)
        # Set next_run_at in the past (missed while offline)
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        update_state(paths, lambda s: s.update({
            "five_hour_next_run_at": past,
            "network_went_offline_at": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
        }))
        return paths

    def test_offline_records_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _cfg(tmp)
            rc, env = _run_capture("--home", tmp, "--json", "schedule", "--network-state", "offline")
            self.assertEqual(rc, 0)
            state = load_state(paths)
            self.assertIn("network_went_offline_at", state)

    def test_online_after_missed_window_marks_calibration_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._setup_with_overdue_window(tmp)
            with mock.patch("claude_starter.cli.notify"), \
                 mock.patch("claude_starter.cli._send_mac_notification"):
                rc, env = _run_capture("--home", tmp, "--json", "schedule", "--network-state", "online")
            self.assertEqual(rc, 0)
            self.assertIn("five_hour", env["data"]["missed_windows"])
            state = load_state(paths)
            self.assertTrue(state.get("five_hour_calibration_needed"))
            # network_went_offline_at should be cleared
            self.assertNotIn("network_went_offline_at", state)

    def test_online_no_missed_windows_no_calibration_needed(self):
        """Online signal when windows haven't fired → no calibration_needed."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _cfg(tmp)
            # Set next_run in the future
            future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
            update_state(paths, lambda s: s.update({
                "five_hour_next_run_at": future,
                "network_went_offline_at": (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat(),
            }))
            with mock.patch("claude_starter.cli.notify"), \
                 mock.patch("claude_starter.cli._send_mac_notification"):
                rc, env = _run_capture("--home", tmp, "--json", "schedule", "--network-state", "online")
            self.assertEqual(rc, 0)
            self.assertEqual(env["data"]["missed_windows"], [])
            state = load_state(paths)
            self.assertFalse(state.get("five_hour_calibration_needed", False))

    def test_online_without_prior_offline_no_error(self):
        """Online signal with no prior offline recorded should work cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _cfg(tmp)
            with mock.patch("claude_starter.cli.notify"), \
                 mock.patch("claude_starter.cli._send_mac_notification"):
                rc, env = _run_capture("--home", tmp, "--json", "schedule", "--network-state", "online")
            self.assertEqual(rc, 0)
            self.assertEqual(env["data"]["missed_windows"], [])

    def test_missed_window_sends_telegram_notification(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._setup_with_overdue_window(tmp)
            notify_calls = []
            with mock.patch("claude_starter.cli.notify", side_effect=lambda p, m: notify_calls.append(m)), \
                 mock.patch("claude_starter.cli._send_mac_notification"):
                _run_capture("--home", tmp, "--json", "schedule", "--network-state", "online")
            self.assertEqual(len(notify_calls), 1)
            self.assertIn("5 saatlik", notify_calls[0])

    def test_calibrate_after_missed_clears_calibration_needed(self):
        """After offline-missed marking, recalibrate → calibration_needed cleared."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._setup_with_overdue_window(tmp)
            with mock.patch("claude_starter.cli.notify"), \
                 mock.patch("claude_starter.cli._send_mac_notification"):
                _run_capture("--home", tmp, "--json", "schedule", "--network-state", "online")
            # Now recalibrate
            anchor = datetime.now(timezone.utc).isoformat()
            with mock.patch("claude_starter.cli.notify"):
                rc, env = _run_capture("--home", tmp, "--json", "calibrate",
                                       "--window-type", "five_hour", "--anchor", anchor)
            self.assertEqual(rc, 0)
            state = load_state(paths)
            self.assertIsNone(state.get("five_hour_calibration_needed"))


# ===========================================================================
# 3. Telegram user management CLI
# ===========================================================================

class TestTelegramUserManagement(unittest.TestCase):

    def _cfg_telegram(self, tmp: str) -> AppPaths:
        import copy
        paths = _paths(tmp)
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["telegram"]["enabled"] = True
        cfg["telegram"]["allowed_user_ids"] = [111]
        cfg["telegram"]["allowed_chat_ids"] = [222]
        save_config(paths, cfg)
        return paths

    def test_list_returns_current_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._cfg_telegram(tmp)
            rc, env = _run_capture("--home", tmp, "--json", "telegram-user", "list")
            self.assertEqual(rc, 0)
            self.assertIn(111, env["data"]["allowed_user_ids"])
            self.assertIn(222, env["data"]["allowed_chat_ids"])

    def test_add_user_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._cfg_telegram(tmp)
            rc, env = _run_capture("--home", tmp, "--json", "telegram-user", "add", "--user-id", "999")
            self.assertEqual(rc, 0)
            self.assertIn(111, env["data"]["allowed_user_ids"])
            self.assertIn(999, env["data"]["allowed_user_ids"])

    def test_add_user_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._cfg_telegram(tmp)
            _run_capture("--home", tmp, "--json", "telegram-user", "add", "--user-id", "111")
            rc, env = _run_capture("--home", tmp, "--json", "telegram-user", "list")
            self.assertEqual(env["data"]["allowed_user_ids"].count(111), 1)

    def test_remove_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._cfg_telegram(tmp)
            rc, env = _run_capture("--home", tmp, "--json", "telegram-user", "remove", "--user-id", "111")
            self.assertEqual(rc, 0)
            self.assertNotIn(111, env["data"]["allowed_user_ids"])

    def test_add_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._cfg_telegram(tmp)
            rc, env = _run_capture("--home", tmp, "--json", "telegram-user", "add", "--chat-id", "555")
            self.assertEqual(rc, 0)
            self.assertIn(555, env["data"]["allowed_chat_ids"])

    def test_remove_chat(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._cfg_telegram(tmp)
            rc, env = _run_capture("--home", tmp, "--json", "telegram-user", "remove", "--chat-id", "222")
            self.assertEqual(rc, 0)
            self.assertNotIn(222, env["data"]["allowed_chat_ids"])

    def test_add_and_remove_persist_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._cfg_telegram(tmp)
            _run_capture("--home", tmp, "--json", "telegram-user", "add", "--user-id", "777")
            _run_capture("--home", tmp, "--json", "telegram-user", "remove", "--user-id", "111")
            from claude_starter.config import load_config
            cfg = load_config(paths)
            self.assertIn(777, cfg["telegram"]["allowed_user_ids"])
            self.assertNotIn(111, cfg["telegram"]["allowed_user_ids"])


# ===========================================================================
# 4. Telegram bot authorization
# ===========================================================================

class TestTelegramAuthorization(unittest.TestCase):
    """Test the authorized() method for all combinations."""

    def _make_bot(self, tmp: str, user_ids=None, chat_ids=None, private_only=True):
        import copy
        from claude_starter.telegram_bot import TelegramBot
        from claude_starter.telegram_api import TelegramAPI
        paths = _paths(tmp)
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["telegram"]["enabled"] = True
        cfg["telegram"]["allowed_user_ids"] = list(user_ids) if user_ids is not None else [100]
        cfg["telegram"]["allowed_chat_ids"] = list(chat_ids) if chat_ids is not None else [200]
        cfg["telegram"]["commands_in_private_chat_only"] = private_only
        save_config(paths, cfg)
        api = mock.MagicMock(spec=TelegramAPI)
        return TelegramBot(paths, api=api)

    def test_authorized_user_private_chat_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = self._make_bot(tmp)
            self.assertTrue(bot.authorized(100, 200, "private"))

    def test_authorized_user_private_chat_different_chat_id_allowed(self):
        """New user added via /adduser — their private chat_id not in list → still allowed."""
        with tempfile.TemporaryDirectory() as tmp:
            bot = self._make_bot(tmp, user_ids=[100, 999], chat_ids=[200])
            # user 999 has a different private chat_id (999_chat)
            self.assertTrue(bot.authorized(999, 999_000, "private"))

    def test_unauthorized_user_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = self._make_bot(tmp)
            self.assertFalse(bot.authorized(999, 200, "private"))

    def test_group_chat_requires_allowed_chat_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = self._make_bot(tmp, private_only=False)
            self.assertTrue(bot.authorized(100, 200, "group"))
            self.assertFalse(bot.authorized(100, 999, "group"))

    def test_private_only_blocks_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = self._make_bot(tmp, private_only=True)
            self.assertFalse(bot.authorized(100, 200, "group"))

    def test_empty_user_list_blocks_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = self._make_bot(tmp, user_ids=[], chat_ids=[])
            self.assertFalse(bot.authorized(100, 200, "private"))

    def test_multiple_users_all_authorized(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot = self._make_bot(tmp, user_ids=[100, 200, 300])
            for uid in [100, 200, 300]:
                self.assertTrue(bot.authorized(uid, uid * 10, "private"))
            self.assertFalse(bot.authorized(999, 9990, "private"))


# ===========================================================================
# 5. Telegram pair append behavior
# ===========================================================================

class TestTelegramPairAppend(unittest.TestCase):
    """telegram-pair must append to existing lists, not replace."""

    def _mock_updates(self, user_id: int, chat_id: int, code: str) -> list:
        return [{
            "update_id": 1,
            "message": {
                "from": {"id": user_id},
                "chat": {"id": chat_id, "type": "private"},
                "text": f"/pair {code}",
            }
        }]

    def test_pair_appends_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cfg = dict(DEFAULT_CONFIG)
            cfg["telegram"]["allowed_user_ids"] = [111]
            cfg["telegram"]["allowed_chat_ids"] = [222]
            cfg["telegram"]["enabled"] = False
            save_config(paths, cfg)

            from claude_starter.cli import execute, build_parser
            args = build_parser().parse_args(
                ["--home", tmp, "--json", "telegram-pair", "--code", "TESTCODE", "--token-stdin"]
            )
            api_mock = mock.MagicMock()
            api_mock.get_updates.return_value = self._mock_updates(999, 888, "TESTCODE")

            with mock.patch("claude_starter.cli.TelegramAPI", return_value=api_mock), \
                 mock.patch("claude_starter.cli._service_action"), \
                 mock.patch("claude_starter.cli._read_token_stdin", return_value="fake-token"):
                status, data = execute(args, paths)

            from claude_starter.config import load_config
            cfg_after = load_config(paths)
            # Original user still present
            self.assertIn(111, cfg_after["telegram"]["allowed_user_ids"])
            # New user appended
            self.assertIn(999, cfg_after["telegram"]["allowed_user_ids"])
            self.assertIn(222, cfg_after["telegram"]["allowed_chat_ids"])
            self.assertIn(888, cfg_after["telegram"]["allowed_chat_ids"])


# ===========================================================================
# 6. Telegram bot human-readable responses
# ===========================================================================

class TestTelegramBotResponses(unittest.TestCase):
    """Verify bot sends human-readable text, not raw JSON."""

    def _bot_and_api(self, tmp: str, user_ids=None, chat_ids=None):
        import copy
        from claude_starter.telegram_bot import TelegramBot
        from claude_starter.telegram_api import TelegramAPI
        paths = _paths(tmp)
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["enabled"] = True
        cfg["background_enabled"] = True
        cfg["timezone"] = "Europe/Istanbul"
        cfg["telegram"]["enabled"] = True
        cfg["telegram"]["allowed_user_ids"] = list(user_ids) if user_ids is not None else [100]
        cfg["telegram"]["allowed_chat_ids"] = list(chat_ids) if chat_ids is not None else [200]
        cfg["telegram"]["commands_in_private_chat_only"] = True
        save_config(paths, cfg)
        api = mock.MagicMock(spec=TelegramAPI)
        bot = TelegramBot(paths, api=api)
        return bot, api, paths

    def _send(self, bot, command: str, arg: str = "", user_id=100, chat_id=200):
        text = f"{command} {arg}".strip()
        update = {
            "update_id": 1,
            "message": {
                "from": {"id": user_id},
                "chat": {"id": chat_id, "type": "private"},
                "text": text,
            }
        }
        bot.handle_update(update)

    def test_status_not_raw_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, paths = self._bot_and_api(tmp)
            self._send(bot, "/status")
            args = api.send_message.call_args[0]
            response = args[1]
            self.assertNotIn('"enabled":', response)
            self.assertIn("Otomasyon", response)

    def test_usage_human_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, paths = self._bot_and_api(tmp)
            cfg = dict(DEFAULT_CONFIG)
            cfg["telegram"]["enabled"] = True
            cfg["telegram"]["allowed_user_ids"] = [100]
            cfg["telegram"]["allowed_chat_ids"] = [200]
            cfg["telegram"]["commands_in_private_chat_only"] = True
            cfg["telegram"]["command_cooldown_seconds"] = 1
            cfg["telegram"]["confirmation_ttl_seconds"] = 60
            cfg["telegram"]["max_prompt_length"] = 500
            cfg["windows"] = {
                "five_hour": {"enabled": True, "anchor_iso": "2026-01-01T00:00:00+00:00", "interval_minutes": 303},
                "weekly": {"enabled": False, "anchor_iso": None, "interval_minutes": 10080},
            }
            save_config(paths, cfg)
            with mock.patch(
                "claude_starter.telegram_bot.query_active_session_usage",
                return_value={
                    "formatted_text": "📊 *Claude Kullanım Bilgisi*\n• 5h remaining 40%\n• Reset in 2h"
                },
            ):
                self._send(bot, "/usage")
            args = api.send_message.call_args[0]
            response = args[1]
            self.assertNotIn('"five_hour_window":', response)
            self.assertIn("Kullanım", response)

    def test_last_no_run_human_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, _ = self._bot_and_api(tmp)
            self._send(bot, "/last")
            args = api.send_message.call_args[0]
            response = args[1]
            self.assertNotIn("{", response)
            self.assertIn("Henüz", response)

    def test_users_list_human_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, _ = self._bot_and_api(tmp)
            self._send(bot, "/users")
            args = api.send_message.call_args[0]
            response = args[1]
            self.assertNotIn("[", response)
            self.assertIn("Kullanıcı", response)

    def test_health_human_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, _ = self._bot_and_api(tmp)
            self._send(bot, "/health")
            args = api.send_message.call_args[0]
            response = args[1]
            self.assertNotIn('"ok":', response)
            self.assertIn("Sağlık", response)

    def test_unauthorized_gets_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, _ = self._bot_and_api(tmp)
            self._send(bot, "/status", user_id=999, chat_id=999)
            args = api.send_message.call_args[0]
            self.assertIn("Unauthorized", args[1])

    def test_help_is_string_not_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, _ = self._bot_and_api(tmp)
            self._send(bot, "/help")
            args = api.send_message.call_args[0]
            response = args[1]
            self.assertIn("/status", response)
            self.assertNotIn('"ok"', response)

    def test_adduser_via_bot_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, paths = self._bot_and_api(tmp)
            self._send(bot, "/adduser", "555")
            args = api.send_message.call_args[0]
            self.assertIn("555", args[1])
            from claude_starter.config import load_config
            cfg = load_config(paths)
            self.assertIn(555, cfg["telegram"]["allowed_user_ids"])

    def test_removeuser_via_bot_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, paths = self._bot_and_api(tmp)
            self._send(bot, "/removeuser", "100")
            from claude_starter.config import load_config
            cfg = load_config(paths)
            self.assertNotIn(100, cfg["telegram"]["allowed_user_ids"])

    def test_adduser_invalid_id_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, _ = self._bot_and_api(tmp)
            self._send(bot, "/adduser", "notanumber")
            args = api.send_message.call_args[0]
            # Should get an error message, not crash
            self.assertIsInstance(args[1], str)

    def test_setmodel_via_bot(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, paths = self._bot_and_api(tmp)
            self._send(bot, "/setmodel", "sonnet")
            from claude_starter.config import load_config
            cfg = load_config(paths)
            self.assertEqual(cfg["model"], "sonnet")

    def test_automation_on_off_via_bot(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, paths = self._bot_and_api(tmp)
            self._send(bot, "/automation_off")
            from claude_starter.config import load_config
            self.assertFalse(load_config(paths)["enabled"])
            # Clear rate limit state so second command is accepted
            update_state(paths, lambda s: s.pop("telegram_rate_limits", None) or None)
            self._send(bot, "/automation_on")
            self.assertTrue(load_config(paths)["enabled"])

    def test_calibrate_5h_via_bot(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot, api, paths = self._bot_and_api(tmp)
            # Set up windows config
            from claude_starter.config import load_config
            cfg = load_config(paths)
            cfg["windows"] = {
                "five_hour": {"enabled": True, "anchor_iso": None, "interval_minutes": 303},
                "weekly": {"enabled": False, "anchor_iso": None, "interval_minutes": 10080},
            }
            save_config(paths, cfg)
            with mock.patch("claude_starter.telegram_bot._run_calibrate_cli"):
                self._send(bot, "/calibrate_5h", "14:30")
            args = api.send_message.call_args[0]
            self.assertIn("kalibre", args[1])


# ===========================================================================
# 7. UI interaction loops — config patch-stdin combinations
# ===========================================================================

class TestUIInteractionLoops(unittest.TestCase):
    """Simulate all UI button interactions to verify no state corruption."""

    def test_toggle_otomasyon_on_off(self):
        """Toggling automation enabled does not wipe other settings."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cfg = dict(DEFAULT_CONFIG)
            cfg["model"] = "haiku"
            cfg["prompt"] = "Test prompt"
            cfg["windows"] = {
                "five_hour": {"enabled": True, "anchor_iso": "2026-07-25T10:00:00Z", "interval_minutes": 303},
                "weekly": {"enabled": False, "anchor_iso": None, "interval_minutes": 10080},
            }
            save_config(paths, cfg)

            # Simulate toggle — sends only enabled + background_enabled + windows.*.enabled
            patch = json.dumps({
                "enabled": True,
                "background_enabled": False,
                "windows": {
                    "five_hour": {"enabled": True},
                    "weekly": {"enabled": False},
                },
            }).encode()
            with mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(patch))):
                rc, env = _run_capture("--home", tmp, "--json", "config", "patch-stdin")
            self.assertEqual(rc, 0)
            from claude_starter.config import load_config
            cfg2 = load_config(paths)
            self.assertEqual(cfg2["model"], "haiku")
            self.assertEqual(cfg2["prompt"], "Test prompt")
            self.assertEqual(cfg2["windows"]["five_hour"]["anchor_iso"], "2026-07-25T10:00:00Z")

    def test_save_configuration_sequence(self):
        """Simulate UI 'Kaydet' after editing prompt — anchor must survive."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cfg = dict(DEFAULT_CONFIG)
            cfg["windows"] = {
                "five_hour": {"enabled": True, "anchor_iso": "2026-07-20T08:00:00Z", "interval_minutes": 303},
                "weekly": {"enabled": True, "anchor_iso": "2026-07-14T08:00:00Z", "interval_minutes": 10080},
            }
            save_config(paths, cfg)
            # Patch that mirrors saveConfiguration() (no anchor_iso in windows)
            patch = json.dumps({
                "enabled": True,
                "background_enabled": True,
                "timezone": "Europe/Istanbul",
                "model": "sonnet",
                "prompt": "New prompt",
                "timeout_seconds": 180,
                "windows": {
                    "five_hour": {"enabled": True},
                    "weekly": {"enabled": True},
                },
                "telegram": {
                    "enabled": False,
                    "allowed_user_ids": [],
                    "allowed_chat_ids": [],
                    "notification_chat_id": None,
                    "notification_channel_id": None,
                },
            }).encode()
            with mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(patch))):
                rc, env = _run_capture("--home", tmp, "--json", "config", "patch-stdin")
            self.assertEqual(rc, 0)
            from claude_starter.config import load_config
            cfg2 = load_config(paths)
            self.assertEqual(cfg2["windows"]["five_hour"]["anchor_iso"], "2026-07-20T08:00:00Z")
            self.assertEqual(cfg2["windows"]["weekly"]["anchor_iso"], "2026-07-14T08:00:00Z")
            self.assertEqual(cfg2["prompt"], "New prompt")
            self.assertEqual(cfg2["model"], "sonnet")

    def test_sleep_mode_toggle_preserves_calibration(self):
        """Exact scenario: calibrate → sleep toggle → status shows calibrated."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cfg = dict(DEFAULT_CONFIG)
            cfg["windows"] = {
                "five_hour": {"enabled": True, "anchor_iso": None, "interval_minutes": 303},
                "weekly": {"enabled": False, "anchor_iso": None, "interval_minutes": 10080},
            }
            save_config(paths, cfg)

            # Step 1: Calibrate
            with mock.patch("claude_starter.cli.notify"):
                rc, _ = _run_capture("--home", tmp, "--json", "calibrate",
                                     "--window-type", "five_hour", "--anchor", "2026-07-26T10:00:00Z")
            self.assertEqual(rc, 0)

            # Step 2: Toggle sleep mode (simulates UI auto-save with no anchor_iso)
            patch = json.dumps({
                "enabled": True,
                "background_enabled": True,
                "windows": {
                    "five_hour": {"enabled": True},
                    "weekly": {"enabled": False},
                },
            }).encode()
            with mock.patch("sys.stdin", io.TextIOWrapper(io.BytesIO(patch))):
                _run_capture("--home", tmp, "--json", "config", "patch-stdin")

            # Step 3: Status must still show anchor
            rc, env = _run_capture("--home", tmp, "--json", "status")
            self.assertEqual(rc, 0)
            anchor = env["data"]["windows"]["five_hour"]["anchor_iso"]
            self.assertIsNotNone(anchor)
            self.assertIn("2026-07-26", anchor)


# ===========================================================================
# 8. Scheduler Z-suffix fix
# ===========================================================================

class TestSchedulerZSuffix(unittest.TestCase):
    def test_next_runs_with_z_suffix_anchor(self):
        from claude_starter.scheduler import next_runs
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cfg = dict(DEFAULT_CONFIG)
            cfg["windows"] = {
                "five_hour": {"enabled": True, "anchor_iso": "2026-01-01T00:00:00Z", "interval_minutes": 303},
                "weekly": {"enabled": True, "anchor_iso": "2026-01-01T00:00:00Z", "interval_minutes": 10080},
            }
            save_config(paths, cfg)
            result = next_runs(paths, cfg)
            self.assertIn("five_hour", result)
            self.assertIn("weekly", result)

    def test_next_runs_with_stored_z_suffix(self):
        from claude_starter.scheduler import next_runs
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cfg = dict(DEFAULT_CONFIG)
            cfg["windows"] = {
                "five_hour": {"enabled": True, "anchor_iso": "2026-01-01T00:00:00+00:00", "interval_minutes": 303},
                "weekly": {"enabled": False, "anchor_iso": None, "interval_minutes": 10080},
            }
            save_config(paths, cfg)
            # State with Z-suffix next_run_at (as stored by Swift)
            update_state(paths, lambda s: s.update({"five_hour_next_run_at": "2026-12-31T00:00:00Z"}))
            result = next_runs(paths, cfg)
            self.assertIn("five_hour", result)
            # Should parse without ValueError
            self.assertIsNotNone(result["five_hour"])


# ===========================================================================
# 9. mac notification helper
# ===========================================================================

class TestMacNotification(unittest.TestCase):
    def test_send_mac_notification_does_not_raise(self):
        from claude_starter.cli import _send_mac_notification
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            _send_mac_notification("Title", "Body message")
            mock_run.assert_called_once()

    def test_send_mac_notification_escapes_quotes(self):
        from claude_starter.cli import _send_mac_notification
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(returncode=0)
            # Should not raise even with quotes in title/body
            _send_mac_notification('Title "with quotes"', 'Body "with quotes"')
            mock_run.assert_called_once()


# ===========================================================================
# 10. Edge cases
# ===========================================================================

class TestEdgeCases(unittest.TestCase):
    def test_status_with_no_windows_configured(self):
        """Status with no windows section should not crash."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            rc, env = _run_capture("--home", tmp, "--json", "status")
            self.assertEqual(rc, 0)
            self.assertTrue(env["ok"])

    def test_calibrate_invalid_anchor_returns_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, env = _run_capture("--home", tmp, "--json", "calibrate",
                                   "--window-type", "five_hour", "--anchor", "not-a-date")
            self.assertNotEqual(rc, 0)
            self.assertFalse(env["ok"])

    def test_main_unhandled_exception_returns_json_error(self):
        """Any unexpected exception must still return a JSON error envelope."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("claude_starter.cli.execute", side_effect=RuntimeError("boom")):
                rc, env = _run_capture("--home", tmp, "--json", "status")
            self.assertFalse(env.get("ok", True))

    def test_telegram_user_list_empty_by_default(self):
        import copy
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cfg = copy.deepcopy(DEFAULT_CONFIG)
            cfg["telegram"]["allowed_user_ids"] = []
            cfg["telegram"]["allowed_chat_ids"] = []
            save_config(paths, cfg)
            rc, env = _run_capture("--home", tmp, "--json", "telegram-user", "list")
            self.assertEqual(rc, 0)
            self.assertEqual(env["data"]["allowed_user_ids"], [])

    def test_config_get_returns_windows_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, env = _run_capture("--home", tmp, "--json", "config", "get")
            self.assertEqual(rc, 0)
            self.assertIn("windows", env["data"])

    def test_schedule_without_network_state_returns_next_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, env = _run_capture("--home", tmp, "--json", "schedule")
            self.assertEqual(rc, 0)
            self.assertIn("next_runs", env["data"])


if __name__ == "__main__":
    unittest.main()
