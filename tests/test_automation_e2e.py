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

FAKE = """#!{python}
import json, sys
if "--version" in sys.argv:
    print("2.2.e2e")
elif "--help" in sys.argv:
    print(
        "--output-format --model --settings --tools "
        "--setting-sources --mcp-config --strict-mcp-config"
    )
elif "auth" in sys.argv:
    print(json.dumps({{"authenticated": True, "method": "oauth"}}))
else:
    print(json.dumps({{
        "result": "OK",
        "model": "claude-haiku-test",
        "rate_limits": {{"five_hour": {{"used_percentage": 3.0, "resets_at": 2000000000}}}}
    }}))
"""


class AutomationE2ETests(unittest.TestCase):
    def test_startup_automation_respects_window_and_restarts_after_due(self) -> None:
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
            config["enabled"] = True
            save_config(paths, config)

            environment = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
            with mock.patch.dict(os.environ, environment, clear=False):
                first = io.StringIO()
                with redirect_stdout(first):
                    code = main(["--home", str(paths.base), "--json", "run", "--automatic"])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(first.getvalue())["status"], "success")

                second = io.StringIO()
                with redirect_stdout(second):
                    code = main(["--home", str(paths.base), "--json", "run", "--automatic"])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(second.getvalue())["status"], "not_due")

                update_state(
                    paths,
                    lambda state: state.__setitem__(
                        "next_window_run_at",
                        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                    ),
                )
                third = io.StringIO()
                with redirect_stdout(third):
                    code = main(["--home", str(paths.base), "--json", "run", "--automatic"])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(third.getvalue())["status"], "success")

    def test_connectivity_pending_is_rescheduled_when_online(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            config = json.loads(json.dumps(DEFAULT_CONFIG))
            config["enabled"] = True
            save_config(paths, config)

            with mock.patch(
                "claude_starter.cli.run_claude",
                side_effect=AppError(ErrorCode.NETWORK_UNAVAILABLE),
            ):
                output = io.StringIO()
                with redirect_stdout(output):
                    code = main(["--home", str(paths.base), "--json", "run", "--automatic"])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output.getvalue())["status"], "pending_connectivity")

            update_state(
                paths,
                lambda state: state.__setitem__(
                    "next_automatic_retry_at", "2100-01-01T00:00:00+00:00"
                ),
            )
            output = io.StringIO()
            with redirect_stdout(output):
                code = main(
                    [
                        "--home",
                        str(paths.base),
                        "--json",
                        "schedule",
                        "--network-state",
                        "online",
                    ]
                )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["status"], "connectivity_recorded")
            retry = load_state(paths)["next_automatic_retry_at"]
            self.assertIsNotNone(retry)
            self.assertLess(
                datetime.fromisoformat(retry),
                datetime.now(timezone.utc) + timedelta(minutes=1),
            )
