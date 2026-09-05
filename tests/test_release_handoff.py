from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter.installation import APP_NAME, SystemServices
from claude_starter.paths import AppPaths


class ReleaseWorkerHandoffTests(unittest.TestCase):
    def test_only_this_installations_verified_workers_are_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory) / "runtime-home")
            paths.ensure()
            paths.bot_lock.write_text("1234")
            app = Path(directory) / APP_NAME
            services = SystemServices(paths, app, Path(directory) / "agents")
            listing = (
                f"1234 python -m claude_starter --home {paths.base} --json telegram-bot\n"
                "1235 python -m claude_starter --home /other --json telegram-bot\n"
                f"1236 {app}/Contents/Helpers/ClaudeWindowStarterAgent telegram\n"
                "1237 /other/ClaudeWindowStarterAgent telegram\n"
            )
            with (
                mock.patch.object(services, "loaded", return_value=False),
                mock.patch("claude_starter.installation.run_checked", return_value=listing),
                mock.patch.object(services, "_terminate") as terminate,
            ):
                services.stop()
            self.assertEqual({call.args[0] for call in terminate.call_args_list}, {1234, 1236})

    def test_stale_pid_with_different_task_is_not_terminated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            paths.bot_lock.write_text("1234")
            services = SystemServices(paths, paths.base / APP_NAME, paths.base / "agents")
            with (
                mock.patch.object(services, "loaded", return_value=False),
                mock.patch(
                    "claude_starter.installation.run_checked", return_value="1234 unrelated\n"
                ),
                mock.patch.object(services, "_terminate") as terminate,
            ):
                services.stop()
            terminate.assert_not_called()
