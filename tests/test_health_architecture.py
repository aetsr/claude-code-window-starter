from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from claude_starter.errors import AppError, ErrorCode
from claude_starter.health import diagnose, health_report
from claude_starter.paths import AppPaths


class ArchitectureTests(unittest.TestCase):
    def test_arm64_and_x86_64_paths_are_supported(self) -> None:
        for architecture in ("aarch64", "arm64", "x86_64"):
            with (
                self.subTest(architecture=architecture),
                tempfile.TemporaryDirectory() as directory,
            ):
                with mock.patch("platform.machine", return_value=architecture):
                    report = diagnose(AppPaths(Path(directory)))
                    self.assertEqual(report["environment"]["machine"], architecture)

    def test_unknown_architecture_stops_safely(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch("platform.machine", return_value="mips"),
        ):
            with self.assertRaises(AppError) as context:
                diagnose(AppPaths(Path(directory)))
        self.assertEqual(context.exception.code, ErrorCode.UNSUPPORTED_ARCH)

    def test_empty_credential_placeholder_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = AppPaths(Path(directory))
            paths.ensure()
            placeholder = paths.secrets_dir / "claude_oauth_token"
            placeholder.touch(mode=0o600)
            report = health_report(paths, include_services=False)
        self.assertFalse(report["checks"]["oauth_credential"]["configured"])


if __name__ == "__main__":
    unittest.main()
