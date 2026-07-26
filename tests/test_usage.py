from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter import usage
from claude_starter.config import DEFAULT_CONFIG
from claude_starter.errors import AppError, ErrorCode
from claude_starter.paths import AppPaths
from claude_starter.usage import (
    build_usage_argv,
    extract_usage_text,
    format_usage_message,
    prepare_usage_workspace,
    query_usage,
    run_usage_session,
    strip_ansi,
    suffix_delta,
    trust_prompt_is_for_workspace,
)

SAFE_HELP = (
    "--no-chrome --permission-mode dontAsk --tools "
    "--mcp-config --strict-mcp-config"
)
SUCCESS_TRANSCRIPT = """
\x1b]0;Claude Code\x07\x1b[?25l
╭─ Claude Code ─────────────────────────╮
│ Welcome to Claude Code                │
╰───────────────────────────────────────╯
❯ /usage
API Usage Billing
Status Config Usage Stats
Current session
████░░ 40% used
Resets in 2 hours
Current week (all models)
████████░░ 82% used
Resets Jul 31 at 12:00am
Esc to cancel
"""


class FakePtyProcess:
    def __init__(self, snapshots: list[str], *, exit_code: int | None = None) -> None:
        self.snapshots = list(snapshots)
        self.exit_code = exit_code
        self.writes: list[bytes] = []
        self.terminate_calls = 0
        self.close_calls = 0

    def read(self, timeout: float) -> str:
        del timeout
        return self.snapshots.pop(0) if self.snapshots else ""

    def write(self, value: bytes) -> None:
        self.writes.append(value)
        if value == b"/exit\r":
            self.exit_code = 0

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self, grace_seconds: float = 1.0) -> None:
        del grace_seconds
        self.terminate_calls += 1
        if self.exit_code is None:
            self.exit_code = -15

    def close(self) -> None:
        self.close_calls += 1


class UsageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = AppPaths(Path(self.temporary.name))
        self.paths.ensure()
        self.config = json.loads(json.dumps(DEFAULT_CONFIG))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _run_fake(self, fake: FakePtyProcess, timeout: int = 5) -> str:
        with mock.patch("claude_starter.usage._spawn_pty_process", return_value=fake):
            return run_usage_session(
                sys.executable,
                workspace=prepare_usage_workspace(self.paths),
                help_text=SAFE_HELP,
                environment={"HOME": str(Path.home()), "PATH": os.environ["PATH"]},
                timeout_seconds=timeout,
                poll_interval_seconds=0,
            )

    def test_strip_ansi_removes_csi_osc_and_cursor_sequences(self) -> None:
        raw = "\x1b]0;secret title\x07\x1b[31mUsage: 52%\x1b[0m\x1b[2A"
        self.assertEqual(strip_ansi(raw), "Usage: 52%")

    def test_forceful_pty_cleanup_never_uses_blocking_waitpid(self) -> None:
        process = usage._PtyProcess(pid=1234, descriptor=9)
        with (
            mock.patch("claude_starter.usage.os.waitpid", return_value=(0, 0)) as waitpid,
            mock.patch("claude_starter.usage.os.killpg") as killpg,
        ):
            process.terminate(grace_seconds=0)

        self.assertEqual(killpg.call_count, 2)
        self.assertTrue(all(call.args[1] == os.WNOHANG for call in waitpid.call_args_list))

    def test_suffix_delta_prefers_overlap(self) -> None:
        self.assertEqual(
            suffix_delta(
                ["line1", "line2", "line3"],
                ["line2", "line3", "/usage", "5h remaining 40%"],
            ),
            ["/usage", "5h remaining 40%"],
        )

    def test_extracts_real_usage_block_and_ignores_tui_chrome(self) -> None:
        self.assertEqual(
            extract_usage_text("", SUCCESS_TRANSCRIPT),
            (
                "Current session\n"
                "████░░ 40% used\n"
                "Resets in 2 hours\n"
                "Current week (all models)\n"
                "████████░░ 82% used\n"
                "Resets Jul 31 at 12:00am"
            ),
        )

    def test_repeated_redraws_return_one_usage_block(self) -> None:
        output = SUCCESS_TRANSCRIPT + "\x1b[6A" + SUCCESS_TRANSCRIPT
        usage = extract_usage_text("", output)
        self.assertEqual(usage.count("Current session"), 1)
        self.assertEqual(usage.count("Current week"), 1)

    def test_cursor_redraw_and_chrome_concatenation_keep_semantic_fields(self) -> None:
        output = (
            "API Usage Billing\x1b[2KCurrent session\n"
            "40% used\nResets in 2 hours\n"
            "Status Config Usage Stats\x1b[1GCurrent week (all models)\n"
            "82% used\nResets Monday at 12:00am"
        )
        usage = extract_usage_text("", output)
        self.assertIn("Current session", usage)
        self.assertIn("Current week", usage)
        self.assertNotIn("API Usage Billing", usage)

    def test_api_usage_billing_is_never_accepted_as_result(self) -> None:
        output = "Welcome\nAPI Usage Billing\nUsage 70%\nReset in 2 hours\n❯"
        self.assertEqual(extract_usage_text("", output), "")

    def test_incomplete_empty_and_unknown_outputs_are_rejected(self) -> None:
        for output in (
            "",
            "Current session\n40% used",
            "Unknown skill: usage",
            "\x1b[31mCurrent week\x1b[0m\nResets tomorrow",
        ):
            with self.subTest(output=output):
                self.assertEqual(extract_usage_text("", output), "")

    def test_format_usage_message_is_plain_text(self) -> None:
        message = format_usage_message(
            "Current session\n40% used\nResets in 2h\n"
            "Current week\n82% used\nResets Monday"
        )
        self.assertIn("Claude Kullanım Bilgisi", message)
        self.assertIn("• 40% used", message)
        self.assertNotIn("*", message)
        self.assertNotIn("/usage", message)

    def test_workspace_is_app_owned_and_mode_0700(self) -> None:
        workspace = prepare_usage_workspace(self.paths)
        self.assertEqual(workspace, self.paths.usage_workspace.resolve())
        info = workspace.stat()
        self.assertEqual(info.st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o700)
        self.assertEqual(workspace.parent, self.paths.runtime_dir.resolve())

    def test_workspace_symlink_is_rejected(self) -> None:
        target = Path(self.temporary.name) / "elsewhere"
        target.mkdir()
        self.paths.usage_workspace.symlink_to(target, target_is_directory=True)
        with self.assertRaises(AppError) as context:
            prepare_usage_workspace(self.paths)
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_USAGE_UNAVAILABLE)

    def test_safe_argv_uses_absolute_cli_and_required_restrictions(self) -> None:
        argv = build_usage_argv(sys.executable, SAFE_HELP)
        self.assertTrue(Path(argv[0]).is_absolute())
        self.assertIn("--no-chrome", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--mcp-config") + 1], '{"mcpServers":{}}')
        self.assertIn("--strict-mcp-config", argv)

    def test_missing_safe_cli_flag_stops_session(self) -> None:
        with self.assertRaises(AppError) as context:
            build_usage_argv(sys.executable, "--no-chrome")
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_USAGE_UNAVAILABLE)

    def test_session_follows_human_event_order_and_cleans_up(self) -> None:
        workspace = prepare_usage_workspace(self.paths)
        trust = (
            f"Do you trust the files in this folder?\n{workspace}\n"
            "❯ 1. Yes, proceed\n  2. No, exit\n"
        )
        fake = FakePtyProcess([trust, "\n❯ \n", SUCCESS_TRANSCRIPT])
        output = self._run_fake(fake)
        self.assertIn("Current session", output)
        self.assertEqual(fake.writes, [b"\r", b"/usage\r", b"\x1b", b"/exit\r"])
        self.assertEqual(fake.terminate_calls, 1)
        self.assertEqual(fake.close_calls, 1)

    def test_real_stdlib_pty_round_trip_with_fake_cli(self) -> None:
        executable = Path(self.temporary.name) / "fake-claude"
        executable.write_text(
            (
                f"#!{sys.executable}\n"
                "import sys\n"
                "print('Welcome to Claude Code', flush=True)\n"
                "print('❯ ', flush=True)\n"
                "for line in sys.stdin:\n"
                "    command = line.strip().lstrip('\\x1b')\n"
                "    if command == '/usage':\n"
                "        print('Current session', flush=True)\n"
                "        print('40% used', flush=True)\n"
                "        print('Resets in 2 hours', flush=True)\n"
                "        print('Current week (all models)', flush=True)\n"
                "        print('82% used', flush=True)\n"
                "        print('Resets Monday at 12:00am', flush=True)\n"
                "    elif command == '/exit':\n"
                "        raise SystemExit(0)\n"
            ),
            encoding="utf-8",
        )
        executable.chmod(0o700)
        output = run_usage_session(
            str(executable),
            workspace=prepare_usage_workspace(self.paths),
            help_text=SAFE_HELP,
            environment={"HOME": str(Path.home()), "PATH": os.environ["PATH"]},
            timeout_seconds=5,
            poll_interval_seconds=0.02,
        )
        self.assertIn("Current session", output)
        self.assertIn("Current week", output)
        self.assertIn("82% used", extract_usage_text("", output))

    def test_session_never_answers_trust_for_another_directory(self) -> None:
        fake = FakePtyProcess(
            [
                "Do you trust the files in this folder?\n"
                "/Users/someone/another-project\n"
                "❯ 1. Yes, proceed\n"
            ]
        )
        with self.assertRaises(AppError) as context:
            self._run_fake(fake)
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_USAGE_UNAVAILABLE)
        self.assertEqual(fake.writes, [])
        self.assertEqual(fake.terminate_calls, 1)
        self.assertEqual(fake.close_calls, 1)

    def test_trust_prompt_without_displayed_path_is_bound_to_verified_cwd(self) -> None:
        workspace = prepare_usage_workspace(self.paths)
        self.assertTrue(
            trust_prompt_is_for_workspace(
                "Do you trust the files in this folder?\n❯ Yes, proceed",
                workspace,
            )
        )

    def test_not_logged_in_is_classified_and_process_is_cleaned(self) -> None:
        fake = FakePtyProcess(["Not logged in. Run claude auth login."])
        with self.assertRaises(AppError) as context:
            self._run_fake(fake)
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_NOT_AUTHENTICATED)
        self.assertEqual(fake.terminate_calls, 1)
        self.assertEqual(fake.close_calls, 1)

    def test_unknown_usage_is_classified_and_process_is_cleaned(self) -> None:
        fake = FakePtyProcess(["❯ \n", "Unknown skill: usage"])
        with self.assertRaises(AppError) as context:
            self._run_fake(fake)
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_USAGE_UNAVAILABLE)
        self.assertEqual(fake.writes, [b"/usage\r"])
        self.assertEqual(fake.terminate_calls, 1)
        self.assertEqual(fake.close_calls, 1)

    def test_process_exit_without_result_is_classified_and_cleaned(self) -> None:
        fake = FakePtyProcess(["Claude crashed"], exit_code=7)
        with self.assertRaises(AppError) as context:
            self._run_fake(fake)
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_USAGE_UNAVAILABLE)
        self.assertEqual(context.exception.details["returncode"], 7)
        self.assertEqual(fake.terminate_calls, 1)
        self.assertEqual(fake.close_calls, 1)

    def test_startup_timeout_cleans_process_and_descriptor(self) -> None:
        fake = FakePtyProcess(["starting"])
        with (
            mock.patch("claude_starter.usage._spawn_pty_process", return_value=fake),
            mock.patch(
                "claude_starter.usage.time.monotonic",
                side_effect=[0.0, 0.0, 0.0, 2.0],
            ),
        ):
            with self.assertRaises(AppError) as context:
                run_usage_session(
                    sys.executable,
                    workspace=prepare_usage_workspace(self.paths),
                    help_text=SAFE_HELP,
                    environment={"HOME": str(Path.home()), "PATH": os.environ["PATH"]},
                    timeout_seconds=1,
                    poll_interval_seconds=0,
                )
        self.assertEqual(context.exception.code, ErrorCode.TIMEOUT)
        self.assertEqual(fake.terminate_calls, 1)
        self.assertEqual(fake.close_calls, 1)

    def test_query_usage_performs_discovery_lock_workspace_and_pty(self) -> None:
        capabilities = mock.Mock(
            executable=sys.executable,
            prohibited_credentials=[],
            auth_status="authenticated",
            help_text=SAFE_HELP,
        )
        with (
            mock.patch("claude_starter.usage.discover_claude", return_value=capabilities),
            mock.patch(
                "claude_starter.usage.run_usage_session",
                return_value=SUCCESS_TRANSCRIPT,
            ) as session,
        ):
            result = query_usage(self.paths, self.config)
        session.assert_called_once()
        self.assertEqual(
            session.call_args.kwargs["workspace"],
            self.paths.usage_workspace.resolve(),
        )
        self.assertIn("Current session", result["usage_text"])
        self.assertNotIn("*", result["formatted_text"])

    def test_query_usage_rejects_busy_claude_run(self) -> None:
        capabilities = mock.Mock(
            executable=sys.executable,
            prohibited_credentials=[],
            auth_status="authenticated",
            help_text=SAFE_HELP,
        )
        with (
            mock.patch("claude_starter.usage.discover_claude", return_value=capabilities),
            mock.patch(
                "claude_starter.usage.FileLock.acquire",
                side_effect=AppError(ErrorCode.ALREADY_RUNNING),
            ),
        ):
            with self.assertRaises(AppError) as context:
                query_usage(self.paths, self.config)
        self.assertEqual(context.exception.code, ErrorCode.ALREADY_RUNNING)

    def test_query_usage_stops_before_pty_when_subscription_is_logged_out(self) -> None:
        capabilities = mock.Mock(
            executable=sys.executable,
            prohibited_credentials=[],
            auth_status="not_authenticated",
            login_command="claude auth login",
        )
        with (
            mock.patch("claude_starter.usage.discover_claude", return_value=capabilities),
            mock.patch("claude_starter.usage._spawn_pty_process") as spawn,
        ):
            with self.assertRaises(AppError) as context:
                query_usage(self.paths, self.config)
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_NOT_AUTHENTICATED)
        spawn.assert_not_called()

    def test_query_usage_rejects_empty_or_unverified_output(self) -> None:
        capabilities = mock.Mock(
            executable=sys.executable,
            prohibited_credentials=[],
            auth_status="authenticated",
            help_text=SAFE_HELP,
        )
        with (
            mock.patch("claude_starter.usage.discover_claude", return_value=capabilities),
            mock.patch("claude_starter.usage.run_usage_session", return_value="API Usage Billing"),
        ):
            with self.assertRaises(AppError) as context:
                query_usage(self.paths, self.config)
        self.assertEqual(context.exception.code, ErrorCode.CLAUDE_USAGE_UNAVAILABLE)

    def test_usage_implementation_has_no_terminal_or_osascript_automation(self) -> None:
        import claude_starter.usage as usage

        source = Path(usage.__file__).read_text(encoding="utf-8")
        self.assertNotIn("osascript", source.lower())
        self.assertNotIn('application "terminal"', source.lower())
        self.assertNotIn("subprocess", source)


if __name__ == "__main__":
    unittest.main()
