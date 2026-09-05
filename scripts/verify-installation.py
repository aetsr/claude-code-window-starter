"""Exercise a real staged app/backend in temporary paths, without user services."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from claude_starter.installation import APP_NAME, LABELS, Installer, SystemServices
from claude_starter.paths import AppPaths


class IsolatedServices(SystemServices):
    def __init__(self, paths: AppPaths, app: Path, agents: Path) -> None:
        super().__init__(paths, app, agents)
        self.active: set[str] = set()
        self.fail = False

    def loaded(self, label: str) -> bool:
        return label in self.active

    def stop(self) -> None:
        self.active.clear()

    def start(self, labels: list[str]) -> None:
        self.active.update(labels)
        if self.fail:
            self.fail = False
            raise RuntimeError("injected service failure")

    def verify(self) -> None:
        # Keep the real signature check; service operations are intentionally simulated.
        super().verify()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--app", type=Path, required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="cws-clean-install-") as temporary:
        root = Path(temporary).resolve()
        paths = AppPaths(root / "App Support & Data")
        app, agents = root / "Applications" / APP_NAME, root / "LaunchAgents"
        services = IsolatedServices(paths, app, agents)
        installer = Installer(paths, app, agents, services)
        first = installer.stage(args.source.resolve(), args.app.resolve())
        installer.activate(first)
        config = paths.config_file.read_bytes()
        second = installer.stage(args.source.resolve(), args.app.resolve())
        installer.activate(second)
        installer.activate(first)
        if paths.current.resolve() != first or paths.config_file.read_bytes() != config:
            raise RuntimeError("Rollback/config preservation failed")
        services.fail = True
        try:
            installer.activate(second)
        except RuntimeError as exc:
            if str(exc) != "injected service failure":
                raise
        else:
            raise RuntimeError("Expected injected failure")
        if paths.current.resolve() != first or services.active != set(LABELS):
            raise RuntimeError("Failure recovery did not restore the previous installation")
    print("Isolated app/backend install, upgrade, rollback and failure recovery passed.")
    print("Service calls were simulated; no user app, config, credentials or launchd jobs changed.")


if __name__ == "__main__":
    main()
