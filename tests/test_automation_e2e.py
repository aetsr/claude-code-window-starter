from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from claude_starter.cli import main
from claude_starter.config import DEFAULT_CONFIG, save_config
from claude_starter.errors import AppError, ErrorCode
from claude_starter.paths import AppPaths
from claude_starter.state import load_state, update_state
from claude_starter.windows import advance_window

FAKE = """#!{python}
import json, sys
if "--version" in sys.argv:
    print("2.2.e2e")
elif "--help" in sys.argv:
    print(
        "--output-format --model --no-session-persistence --no-chrome "
        "--disable-slash-commands --permission-mode dontAsk --tools "
        "--mcp-config --strict-mcp-config"
    )
elif "auth" in sys.argv:
    print(json.dumps({{"authenticated": True, "method": "oauth"}}))
else:
    print(json.dumps({{
        "result": "OK",
        "model": "claude-haiku-test",
        "usage": {{"input_tokens": 1}}
    }}))
"""


class AutomationE2ETests(unittest.TestCase):
    def test_window_trigger_updates_state_correctly(self) -> None:
        """Test that window-based trigger updates next_run_at and last_triggered_at."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = AppPaths(root / "app")
            paths.ensure()
            bin_dir = root / "bin"
            bin_dir.mkdir()
            executable = bin_dir / "claude"
            executable.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

            config = json.loads(json.dumps(DEFAULT_CONFIG))
            # Set up five-hour window with anchor in the past
            anchor = datetime.now(timezone.utc) - timedelta(hours=6)
            config["windows"]["five_hour"]["enabled"] = True
            config["windows"]["five_hour"]["anchor_iso"] = anchor.isoformat()
            config["windows"]["five_hour"]["interval_minutes"] = 303
            config["enabled"] = True
            save_config(paths, config)

            environment = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
            with mock.patch.dict(os.environ, environment, clear=False):
                # Run with window_type specified
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(
                        ["--home", str(paths.base), "--json", "run", "--window-type", "five_hour"]
                    )
                self.assertEqual(code, 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["status"], "success")

                # Verify state was updated
                state = load_state(paths)
                self.assertIsNotNone(state.get("five_hour_last_triggered_at"))
                self.assertIsNotNone(state.get("five_hour_next_run_at"))
                self.assertIsNone(state.get("five_hour_calibration_needed"))

    def test_calibrate_command_sets_anchor(self) -> None:
        """Test that calibrate command updates anchor_iso and computes next_run_at."""
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            config = json.loads(json.dumps(DEFAULT_CONFIG))
            config["enabled"] = True
            save_config(paths, config)

            # Calibrate with a specific anchor time
            anchor = datetime(2026, 7, 25, 10, 0, 0, tzinfo=timezone.utc)
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(paths.base),
                        "--json",
                        "calibrate",
                        "--window-type",
                        "five_hour",
                        "--anchor",
                        anchor.isoformat(),
                    ]
                )
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["data"]["anchor_iso"], anchor.isoformat())

            # Verify config was updated
            updated_config = json.loads(paths.config_file.read_text())
            self.assertEqual(updated_config["windows"]["five_hour"]["anchor_iso"], anchor.isoformat())

    def test_status_command_shows_window_info(self) -> None:
        """Test that status command displays window countdown and next_run_at."""
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            config = json.loads(json.dumps(DEFAULT_CONFIG))
            anchor = datetime.now(timezone.utc) - timedelta(hours=4)
            config["windows"]["five_hour"]["enabled"] = True
            config["windows"]["five_hour"]["anchor_iso"] = anchor.isoformat()
            config["windows"]["five_hour"]["interval_minutes"] = 303
            save_config(paths, config)

            output = io.StringIO()
            with redirect_stdout(output):
                code = main(["--home", str(paths.base), "--json", "status"])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            data = result["data"]

            # Verify window status is in output
            self.assertIn("windows", data)
            self.assertIn("five_hour", data["windows"])
            five_hour = data["windows"]["five_hour"]
            self.assertTrue(five_hour["enabled"])
            self.assertIsNotNone(five_hour["next_run_at"])
            self.assertIsNotNone(five_hour["countdown"])

    def test_dry_run_with_window_type_doesnt_update_state(self) -> None:
        """Test that dry-run mode doesn't persist state changes."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = AppPaths(root / "app")
            paths.ensure()
            bin_dir = root / "bin"
            bin_dir.mkdir()
            executable = bin_dir / "claude"
            executable.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
            executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

            config = json.loads(json.dumps(DEFAULT_CONFIG))
            anchor = datetime.now(timezone.utc) - timedelta(hours=6)
            config["windows"]["five_hour"]["enabled"] = True
            config["windows"]["five_hour"]["anchor_iso"] = anchor.isoformat()
            config["enabled"] = True
            save_config(paths, config)

            environment = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
            with mock.patch.dict(os.environ, environment, clear=False):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(
                        [
                            "--home",
                            str(paths.base),
                            "--json",
                            "run",
                            "--window-type",
                            "five_hour",
                            "--dry-run",
                        ]
                    )
                self.assertEqual(code, 0)
                result = json.loads(output.getvalue())
                self.assertEqual(result["status"], "dry_run")

                # Verify state was NOT updated
                state = load_state(paths)
                self.assertIsNone(state.get("five_hour_last_triggered_at"))
                self.assertIsNone(state.get("five_hour_next_run_at"))


if __name__ == "__main__":
    unittest.main()
