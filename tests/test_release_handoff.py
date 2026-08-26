from __future__ import annotations

import unittest
from pathlib import Path


class ReleaseWorkerHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]

    def test_install_targets_only_verified_lock_owner_without_pkill(self) -> None:
        install = (self.root / "scripts/install-macos.sh").read_text(encoding="utf-8")
        build = (self.root / "scripts/build-macos-app.sh").read_text(encoding="utf-8")
        self.assertNotIn("pkill", install)
        self.assertNotIn("pkill", build)
        self.assertIn("shared/runtime/telegram.lock", install)
        self.assertIn('" -m claude_starter "', install)
        self.assertIn('" --home $BASE "', install)
        self.assertIn('" telegram-bot "', install)
        self.assertIn('kill -TERM "$worker_pid"', install)
        self.assertIn('" --supervisor-pid "', install)

    def test_install_stops_old_supervisor_before_worker_handoff(self) -> None:
        install = (self.root / "scripts/install-macos.sh").read_text(encoding="utf-8")
        # All existing jobs are booted out, then supervisors killed, then workers terminated,
        # then fresh jobs bootstrapped, then one final legacy worker cleanup.
        # Use the invocation lines (not the function definitions) for ordering checks.
        bootout_loop = "done\nterminate_all_telegram_supervisors"
        initial_handoff = "terminate_stale_telegram_worker\n"
        post_bootstrap_handoff = "terminate_stale_telegram_worker legacy"
        self.assertIn(bootout_loop, install)
        self.assertLess(
            install.index(bootout_loop), install.index(initial_handoff)
        )
        self.assertGreater(
            install.index(post_bootstrap_handoff),
            install.index('launchctl bootstrap "$DOMAIN" "$AGENT_DIR/$label.plist"'),
        )


if __name__ == "__main__":
    unittest.main()
