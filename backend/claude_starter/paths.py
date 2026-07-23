from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppPaths:
    base: Path

    @classmethod
    def discover(cls, override: str | None = None) -> AppPaths:
        value = override or os.environ.get("CLAUDE_STARTER_HOME")
        base = (
            Path(value).expanduser()
            if value
            else Path.home() / ".local/share/claude-window-starter"
        )
        return cls(base.resolve())

    @property
    def shared(self) -> Path:
        return self.base / "shared"

    @property
    def config_dir(self) -> Path:
        return self.shared / "config"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def state_dir(self) -> Path:
        return self.shared / "state"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def log_dir(self) -> Path:
        return self.shared / "logs"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "events.jsonl"

    @property
    def runtime_dir(self) -> Path:
        return self.shared / "runtime"

    @property
    def secrets_dir(self) -> Path:
        return self.shared / "secrets"

    @property
    def run_lock(self) -> Path:
        return self.runtime_dir / "claude.lock"

    @property
    def update_lock(self) -> Path:
        return self.runtime_dir / "update.lock"

    @property
    def bot_lock(self) -> Path:
        return self.runtime_dir / "telegram.lock"

    @property
    def releases(self) -> Path:
        return self.base / "releases"

    @property
    def repo(self) -> Path:
        return self.base / "repo.git"

    @property
    def current(self) -> Path:
        return self.base / "current"

    @property
    def previous(self) -> Path:
        return self.base / "previous"

    def ensure(self) -> None:
        for directory in (
            self.config_dir,
            self.state_dir,
            self.log_dir,
            self.runtime_dir,
            self.secrets_dir,
            self.releases,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
