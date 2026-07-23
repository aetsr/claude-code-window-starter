from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout

from claude_starter.cli import main


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
