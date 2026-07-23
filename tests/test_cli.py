from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from claude_starter.cli import main


class CLITests(unittest.TestCase):
    def test_version_uses_stable_json_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--home", directory, "--json", "version"])
            value = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(value["schema_version"], 1)
            self.assertTrue(value["ok"])

    def test_config_patch_stdin_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with unittest.mock.patch("sys.stdin", io.StringIO('{"unknown": true}')):
                with redirect_stdout(output):
                    code = main(["--home", directory, "--json", "config", "patch-stdin"])
            self.assertEqual(code, 2)

    def test_credential_store_never_echoes_secret(self) -> None:
        secret = "private-value-that-must-not-be-returned"
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with unittest.mock.patch("sys.stdin", io.StringIO(secret + "\n")):
                with redirect_stdout(output):
                    code = main(
                        [
                            "--home",
                            directory,
                            "--json",
                            "credential",
                            "store",
                            "telegram_token",
                        ]
                    )
            self.assertEqual(code, 0)
            self.assertNotIn(secret, output.getvalue())
            credential = Path(directory) / "shared/secrets/telegram_token"
            self.assertEqual(credential.read_text(), secret)
            self.assertEqual(credential.stat().st_mode & 0o777, 0o600)

    def test_disabled_automatic_run_is_clean_skip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--home", directory, "--json", "run", "--automatic"])
            value = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(value["status"], "disabled")
            self.assertFalse(value["data"]["real_request_sent"])


if __name__ == "__main__":
    unittest.main()
