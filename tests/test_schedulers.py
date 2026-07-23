from __future__ import annotations

import json
import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter.cli import _write_launchd_schedule, _write_systemd_schedule
from claude_starter.config import DEFAULT_CONFIG
from claude_starter.paths import AppPaths


class SchedulerArtifactTests(unittest.TestCase):
    def test_systemd_dropin_uses_timezone_and_persistent_timer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = json.loads(json.dumps(DEFAULT_CONFIG))
            config["schedule_time"] = "09:15"
            with mock.patch.dict(os.environ, {"CLAUDE_STARTER_SYSTEMD_USER_DIR": directory}):
                path = _write_systemd_schedule(AppPaths(Path(directory) / "app"), config)
            text = path.read_text()
            self.assertIn("09:15:00 Europe/Istanbul", text)
            self.assertIn("Persistent=true", text)

    def test_launchd_schedule_is_updated_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent.plist"
            path.write_bytes(
                plistlib.dumps(
                    {
                        "Label": "com.openai.claude-window-starter",
                        "ProgramArguments": ["/bin/true"],
                        "StartCalendarInterval": {"Hour": 8, "Minute": 0},
                    }
                )
            )
            config = json.loads(json.dumps(DEFAULT_CONFIG))
            config["schedule_time"] = "17:42"
            environment = {
                "CLAUDE_STARTER_LAUNCHD_PLIST": str(path),
                "CLAUDE_STARTER_SKIP_SERVICE_RESTART": "1",
            }
            with mock.patch.dict(os.environ, environment):
                _write_launchd_schedule(config)
            value = plistlib.loads(path.read_bytes())
            self.assertEqual(value["StartCalendarInterval"], {"Hour": 17, "Minute": 42})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
