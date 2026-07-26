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
            else Path.home() / "Library/Application Support/ClaudeWindowStarter"
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
    def usage_workspace(self) -> Path:
        return self.runtime_dir / "usage-workspace"

    @property
    def run_lock(self) -> Path:
        return self.runtime_dir / "claude.lock"

    @property
    def bot_lock(self) -> Path:
        return self.runtime_dir / "telegram.lock"

    @property
    def usage_status_file(self) -> Path:
        return self.runtime_dir / "usage-status.json"

    @property
    def releases(self) -> Path:
        return self.base / "releases"

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
            self.releases,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
