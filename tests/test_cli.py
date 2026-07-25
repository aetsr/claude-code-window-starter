from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from claude_starter.cli import main
from claude_starter.config import load_config
from claude_starter.paths import AppPaths
from claude_starter.state import load_state


class CLITests(unittest.TestCase):
    def test_version_uses_v2_json_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--home", directory, "--json", "version"])
            value = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(value["schema_version"], 2)
            self.assertTrue(value["ok"])

    def test_config_patch_stdin_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with unittest.mock.patch("sys.stdin", io.StringIO('{"unknown": true}')):
                with redirect_stdout(output):
                    code = main(["--home", directory, "--json", "config", "patch-stdin"])
            self.assertEqual(code, 2)

    def test_disabled_automatic_run_is_clean_skip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--home", directory, "--json", "run", "--automatic"])
            value = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(value["status"], "disabled")
            self.assertFalse(value["data"]["real_request_sent"])

    def test_private_pairing_configures_allowlist_and_sends_confirmation(self) -> None:
        update = {
            "update_id": 44,
            "message": {
                "from": {"id": 12345},
                "chat": {"id": 12345, "type": "private"},
                "text": "/pair ABC12345",
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with (
                unittest.mock.patch("sys.stdin", io.StringIO("token-from-keychain")),
                unittest.mock.patch("claude_starter.cli.TelegramAPI") as api_type,
                redirect_stdout(output),
            ):
                api_type.return_value.get_updates.return_value = [update]
                code = main(
                    [
                        "--home",
                        directory,
                        "--json",
                        "telegram-pair",
                        "--code",
                        "ABC12345",
                        "--token-stdin",
                    ]
                )
            self.assertEqual(code, 0)
            value = json.loads(output.getvalue())
            self.assertTrue(value["data"]["enabled"])
            self.assertIn("service_restarted", value["data"])
            api_type.return_value.send_message.assert_called_once()
            paths = AppPaths(Path(directory))
            config = load_config(paths)
            self.assertTrue(config["telegram"]["enabled"])
            self.assertEqual(config["telegram"]["allowed_user_ids"], [12345])
            self.assertEqual(config["telegram"]["allowed_chat_ids"], [12345])
            self.assertEqual(load_state(paths)["telegram_offset"], 45)

    def test_pairing_rejects_group_and_malformed_ids_without_crashing(self) -> None:
        updates = [
            {
                "update_id": "bad",
                "message": {
                    "from": {"id": "123"},
                    "chat": {"id": 123, "type": "group"},
                    "text": "/pair ABC12345",
                },
            }
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with (
                unittest.mock.patch("sys.stdin", io.StringIO("token-from-keychain")),
                unittest.mock.patch("claude_starter.cli.TelegramAPI") as api_type,
                redirect_stderr(output),
            ):
                api_type.return_value.get_updates.return_value = updates
                code = main(
                    [
                        "--home",
                        directory,
                        "--json",
                        "telegram-pair",
                        "--code",
                        "ABC12345",
                        "--token-stdin",
                    ]
                )
            self.assertEqual(code, 6)
            self.assertEqual(
                json.loads(output.getvalue())["error"]["code"],
                "TELEGRAM_PAIRING_FAILED",
            )
