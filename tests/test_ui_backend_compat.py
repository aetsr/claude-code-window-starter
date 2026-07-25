"""UI↔Backend compatibility tests.

Simulates every user action the macOS app can trigger and verifies the
JSON envelope shape the Swift BackendClient expects.

BackendClient contract (BackendClient.swift):
  - Reads stdout if non-empty, else stderr
  - Decodes as CommandEnvelope: {schema_version, ok, status, error, data}
  - ok=false  → throws nonZero(status_code, error.message)
  - ok=true   → returns envelope for further parsing

AppModel parses:
  status  → parseStatus(data): windows, health, enabled, telegram_enabled ...
  config get → parseConfig(data): timezone, model, prompt, windows ...
  run     → parseRunResult(data): selected_model, response_summary
  calibrate → perform() then refreshStatus
  service telegram → perform(), result shown in statusText
"""
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
from claude_starter.paths import AppPaths
from claude_starter.state import load_state, update_state

# ---------------------------------------------------------------------------
# Fake Claude binary used by run-command tests
# ---------------------------------------------------------------------------
FAKE_CLAUDE = """#!{python}
import json, sys
if "--version" in sys.argv:
    print("2.2.test")
elif "--help" in sys.argv:
    print("--output-format --model --no-session-persistence --no-chrome "
          "--disable-slash-commands --permission-mode dontAsk --tools "
          "--mcp-config --strict-mcp-config")
elif "auth" in sys.argv:
    print(json.dumps({{"authenticated": True, "method": "oauth"}}))
else:
    print(json.dumps({{"result": "OK", "model": "claude-haiku-test",
                       "usage": {{"input_tokens": 1}}}}))
"""


def _make_paths(directory: str) -> AppPaths:
    paths = AppPaths(Path(directory))
    paths.ensure()
    return paths


def _run(args: list[str], *, capture_stderr: bool = False) -> tuple[int, dict]:
    """Run main() and return (exit_code, parsed_json)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out):
        with mock.patch("sys.stderr", err):
            code = main(args)
    # BackendClient reads stdout if non-empty, else stderr
    raw = out.getvalue() or err.getvalue()
    return code, json.loads(raw)


def _enabled_config(paths: AppPaths, **overrides) -> dict:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config["enabled"] = True
    for k, v in overrides.items():
        config[k] = v
    save_config(paths, config)
    return config


# ---------------------------------------------------------------------------
# 1. Envelope shape — every response must satisfy BackendClient contract
# ---------------------------------------------------------------------------
class EnvelopeShapeTests(unittest.TestCase):
    """Every CLI command must return schema_version=3 JSON with ok/status/data."""

    REQUIRED_KEYS = {"schema_version", "ok", "status", "error", "data"}

    def _assert_envelope(self, result: dict, *, ok: bool) -> None:
        self.assertEqual(result.get("schema_version"), 3)
        self.assertEqual(result.get("ok"), ok)
        self.assertIn("status", result)
        missing = self.REQUIRED_KEYS - result.keys()
        self.assertFalse(missing, f"Missing keys: {missing}")

    def test_status_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            code, result = _run(["--home", d, "--json", "status"])
            self.assertEqual(code, 0)
            self._assert_envelope(result, ok=True)

    def test_config_get_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            code, result = _run(["--home", d, "--json", "config", "get"])
            self.assertEqual(code, 0)
            self._assert_envelope(result, ok=True)

    def test_calibrate_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            code, result = _run(["--home", d, "--json", "calibrate",
                                   "--window-type", "five_hour",
                                   "--anchor", "2026-07-25T10:00:00Z"])
            self.assertEqual(code, 0)
            self._assert_envelope(result, ok=True)

    def test_invalid_command_returns_json_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_paths(d)
            code, result = _run(["--home", d, "--json", "calibrate",
                                   "--window-type", "five_hour",
                                   "--anchor", "not-a-date"])
            self.assertNotEqual(code, 0)
            self._assert_envelope(result, ok=False)
            self.assertIsNotNone(result.get("error"))


# ---------------------------------------------------------------------------
# 2. Status response — AppModel.parseStatus() contract
# ---------------------------------------------------------------------------
class StatusResponseTests(unittest.TestCase):
    """status data must contain all fields AppModel.parseStatus() reads."""

    def _get_status_data(self, paths: AppPaths) -> dict:
        code, result = _run(["--home", str(paths.base), "--json", "status"])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        return result["data"]

    def test_status_has_enabled_flag(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            data = self._get_status_data(paths)
            self.assertIn("enabled", data)
            self.assertIn("background_enabled", data)
            self.assertIn("telegram_enabled", data)

    def test_status_has_windows_section(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            data = self._get_status_data(paths)
            self.assertIn("windows", data)
            self.assertIn("five_hour", data["windows"])
            self.assertIn("weekly", data["windows"])

    def test_window_status_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            config = _enabled_config(paths)
            anchor = datetime.now(timezone.utc) - timedelta(hours=2)
            config["windows"]["five_hour"]["anchor_iso"] = anchor.isoformat()
            save_config(paths, config)
            data = self._get_status_data(paths)
            w = data["windows"]["five_hour"]
            for key in ("enabled", "anchor_iso", "next_run_at", "countdown",
                        "last_triggered_at", "last_result", "calibration_needed"):
                self.assertIn(key, w, f"Missing window field: {key}")

    def test_status_has_health_section(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            data = self._get_status_data(paths)
            self.assertIn("health", data)

    def test_countdown_is_string_when_calibrated(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            config = _enabled_config(paths)
            anchor = datetime.now(timezone.utc) - timedelta(hours=1)
            config["windows"]["five_hour"]["anchor_iso"] = anchor.isoformat()
            save_config(paths, config)
            data = self._get_status_data(paths)
            countdown = data["windows"]["five_hour"]["countdown"]
            self.assertIsInstance(countdown, str)
            self.assertNotEqual(countdown, "")

    def test_countdown_is_dash_when_not_calibrated(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            data = self._get_status_data(paths)
            countdown = data["windows"]["five_hour"]["countdown"]
            self.assertEqual(countdown, "—")


# ---------------------------------------------------------------------------
# 3. Config get — AppModel.parseConfig() contract
# ---------------------------------------------------------------------------
class ConfigGetTests(unittest.TestCase):
    """config get data must contain all fields AppModel.parseConfig() reads."""

    def test_config_get_has_all_top_level_fields(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            code, result = _run(["--home", d, "--json", "config", "get"])
            self.assertEqual(code, 0)
            data = result["data"]
            for key in ("timezone", "model", "prompt", "timeout_seconds",
                        "enabled", "background_enabled", "windows", "telegram"):
                self.assertIn(key, data, f"Missing config field: {key}")

    def test_config_get_windows_has_anchor_and_interval(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            code, result = _run(["--home", d, "--json", "config", "get"])
            data = result["data"]
            for wtype in ("five_hour", "weekly"):
                w = data["windows"][wtype]
                self.assertIn("enabled", w)
                self.assertIn("anchor_iso", w)
                self.assertIn("interval_minutes", w)


# ---------------------------------------------------------------------------
# 4. Calibrate — all input formats the macOS app sends
# ---------------------------------------------------------------------------
class CalibrateTests(unittest.TestCase):
    """Calibrate must accept every anchor format the Swift app produces."""

    def _calibrate(self, paths: AppPaths, window_type: str, anchor: str) -> dict:
        code, result = _run(["--home", str(paths.base), "--json", "calibrate",
                               "--window-type", window_type, "--anchor", anchor])
        self.assertEqual(code, 0, f"calibrate failed: {result}")
        self.assertTrue(result["ok"])
        return result

    def test_five_hour_z_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            result = self._calibrate(paths, "five_hour", "2026-07-25T10:00:00Z")
            self.assertEqual(result["data"]["window_type"], "five_hour")
            self.assertIsNotNone(result["data"]["next_run_at"])

    def test_five_hour_plus_zero(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            result = self._calibrate(paths, "five_hour", "2026-07-25T10:00:00+00:00")
            self.assertTrue(result["ok"])

    def test_weekly_z_suffix_full_datetime(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            result = self._calibrate(paths, "weekly", "2026-07-20T09:30:00Z")
            self.assertEqual(result["data"]["window_type"], "weekly")

    def test_calibrate_when_window_disabled(self) -> None:
        """Calibrating a disabled window must not raise — critical edge case."""
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            config = _enabled_config(paths)
            config["windows"]["five_hour"]["enabled"] = False
            save_config(paths, config)
            result = self._calibrate(paths, "five_hour", "2026-07-25T10:00:00Z")
            self.assertTrue(result["ok"])

    def test_calibrate_updates_state_next_run_at(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            self._calibrate(paths, "five_hour", "2026-07-25T10:00:00Z")
            state = load_state(paths)
            self.assertIsNotNone(state.get("five_hour_next_run_at"))
            self.assertIsNone(state.get("five_hour_calibration_needed"))

    def test_calibrate_clears_calibration_needed_flag(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            # Simulate pre-existing calibration_needed flag
            update_state(paths, lambda s: s.__setitem__("five_hour_calibration_needed",
                                                         {"error_message": "stale"}))
            self._calibrate(paths, "five_hour", "2026-07-25T10:00:00Z")
            state = load_state(paths)
            self.assertIsNone(state.get("five_hour_calibration_needed"))

    def test_invalid_anchor_returns_json_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            code, result = _run(["--home", d, "--json", "calibrate",
                                   "--window-type", "five_hour",
                                   "--anchor", "garbage"])
            self.assertNotEqual(code, 0)
            self.assertFalse(result["ok"])
            # Must be parseable JSON (not raw traceback)
            self.assertIn("schema_version", result)


# ---------------------------------------------------------------------------
# 5. Run command — AppModel triggers this via "Şimdi çalıştır" button
# ---------------------------------------------------------------------------
class RunCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp()
        self.paths = _make_paths(self._tmpdir)
        bin_dir = Path(self._tmpdir) / "bin"
        bin_dir.mkdir()
        exe = bin_dir / "claude"
        exe.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
        self._env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
        config = _enabled_config(self.paths)
        anchor = datetime.now(timezone.utc) - timedelta(hours=6)
        config["windows"]["five_hour"]["anchor_iso"] = anchor.isoformat()
        save_config(self.paths, config)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_run_returns_success_with_model(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            code, result = _run(["--home", self._tmpdir, "--json", "run",
                                   "--trigger", "macos_ui"])
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertIn("selected_model", result["data"])

    def test_run_with_window_type_updates_state(self) -> None:
        with mock.patch.dict(os.environ, self._env, clear=False):
            code, result = _run(["--home", self._tmpdir, "--json", "run",
                                   "--window-type", "five_hour",
                                   "--trigger", "background"])
        self.assertEqual(code, 0)
        state = load_state(self.paths)
        self.assertIsNotNone(state.get("five_hour_last_triggered_at"))
        self.assertIsNotNone(state.get("five_hour_next_run_at"))


# ---------------------------------------------------------------------------
# 6. Config patch-stdin — AppModel.saveConfiguration()
# ---------------------------------------------------------------------------
class ConfigPatchTests(unittest.TestCase):
    def _patch(self, paths: AppPaths, patch: dict) -> dict:
        code, result = _run(
            ["--home", str(paths.base), "--json", "config", "patch-stdin"],
            capture_stderr=True,
        )
        # For stdin we need to supply data — use mock
        return result

    def test_config_patch_via_stdin_updates_fields(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            patch = json.dumps({"model": "opus", "timezone": "UTC"}).encode()
            out = io.StringIO()
            with redirect_stdout(out):
                with mock.patch("sys.stdin", io.StringIO(patch.decode())):
                    code = main(["--home", d, "--json", "config", "patch-stdin"])
            result = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(result["ok"])
            self.assertEqual(result["data"]["model"], "opus")
            self.assertEqual(result["data"]["timezone"], "UTC")

    def test_config_patch_with_window_settings(self) -> None:
        """AppModel.saveConfiguration sends windows section — must be accepted."""
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            patch = json.dumps({
                "enabled": True,
                "background_enabled": False,
                "windows": {
                    "five_hour": {
                        "enabled": True,
                        "anchor_iso": "2026-07-25T10:00:00Z",
                        "interval_minutes": 303,
                    },
                    "weekly": {
                        "enabled": False,
                        "anchor_iso": None,
                        "interval_minutes": 10080,
                    },
                },
            })
            out = io.StringIO()
            with redirect_stdout(out):
                with mock.patch("sys.stdin", io.StringIO(patch)):
                    code = main(["--home", d, "--json", "config", "patch-stdin"])
            result = json.loads(out.getvalue())
            self.assertEqual(code, 0, f"patch failed: {result}")
            self.assertTrue(result["ok"])
            self.assertEqual(
                result["data"]["windows"]["five_hour"]["anchor_iso"],
                "2026-07-25T10:00:00Z",
            )


# ---------------------------------------------------------------------------
# 7. Telegram service commands — AppModel.perform(["service", "telegram", ...])
# ---------------------------------------------------------------------------
class TelegramServiceTests(unittest.TestCase):
    """service telegram commands must return valid JSON envelopes."""

    def _service(self, paths: AppPaths, action: str) -> tuple[int, dict]:
        with mock.patch(
            "claude_starter.cli._service_action",
            return_value={"label": "com.test", "action": action, "output": ""},
        ):
            return _run(["--home", str(paths.base), "--json",
                          "service", "telegram", action])

    def test_start_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            code, result = self._service(paths, "start")
            self.assertEqual(code, 0)
            self.assertTrue(result["ok"])

    def test_stop_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            code, result = self._service(paths, "stop")
            self.assertEqual(code, 0)
            self.assertTrue(result["ok"])

    def test_restart_returns_ok(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            paths = _make_paths(d)
            _enabled_config(paths)
            code, result = self._service(paths, "restart")
            self.assertEqual(code, 0)
            self.assertTrue(result["ok"])


# ---------------------------------------------------------------------------
# 8. Error robustness — no command must produce raw traceback on stdout/stderr
# ---------------------------------------------------------------------------
class ErrorRobustnessTests(unittest.TestCase):
    """All errors must be JSON envelopes, never raw Python tracebacks."""

    def _is_json_envelope(self, text: str) -> bool:
        try:
            obj = json.loads(text)
            return isinstance(obj, dict) and "schema_version" in obj
        except (json.JSONDecodeError, ValueError):
            return False

    def _run_capture_all(self, args: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stderr", err):
            code = main(args)
        combined = out.getvalue() or err.getvalue()
        return code, combined

    def test_invalid_anchor_produces_json(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_paths(d)
            code, output = self._run_capture_all(
                ["--home", d, "--json", "calibrate",
                 "--window-type", "five_hour", "--anchor", "bad-date"]
            )
            self.assertNotEqual(code, 0)
            self.assertTrue(self._is_json_envelope(output), f"Not JSON: {output[:200]}")

    def test_unexpected_exception_produces_json(self) -> None:
        """Even an unhandled exception must yield JSON via the catch-all in main()."""
        with tempfile.TemporaryDirectory() as d:
            _make_paths(d)
            with mock.patch(
                "claude_starter.cli.execute",
                side_effect=RuntimeError("simulated unexpected error"),
            ):
                code, output = self._run_capture_all(["--home", d, "--json", "status"])
            self.assertNotEqual(code, 0)
            self.assertTrue(self._is_json_envelope(output),
                            f"Expected JSON envelope, got: {output[:200]}")

    def test_status_on_empty_dir_is_ok(self) -> None:
        """Status on a fresh directory must succeed (creates defaults)."""
        with tempfile.TemporaryDirectory() as d:
            code, output = self._run_capture_all(["--home", d, "--json", "status"])
            self.assertEqual(code, 0)
            self.assertTrue(self._is_json_envelope(output))


if __name__ == "__main__":
    unittest.main()
