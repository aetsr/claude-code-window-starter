from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import AppPaths

SENSITIVE_KEYS = re.compile(
    r"(api[_-]?key|token|secret|password|cookie|authorization|credential|private[_-]?key)",
    re.IGNORECASE,
)
SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*"),
)


def sanitize_text(value: str, limit: int = 1000) -> str:
    cleaned = value
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    cleaned = cleaned.replace("\x00", "")
    return cleaned[:limit]


def sanitize(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {str(k): sanitize(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    return value


def log_event(paths: AppPaths, event: dict[str, Any]) -> None:
    paths.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {"timestamp": datetime.now(timezone.utc).isoformat(), **sanitize(event)}
    descriptor = os.open(paths.log_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps(record, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        os.close(descriptor)


def rotate_logs(paths: AppPaths, retention_days: int) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for path in paths.log_dir.glob("events-*.jsonl"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if modified < cutoff:
                path.unlink()
        except OSError:
            continue
    if paths.log_file.exists() and paths.log_file.stat().st_size > 5 * 1024 * 1024:
        target = paths.log_dir / f"events-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl"
        paths.log_file.replace(target)


def tail_sanitized(path: Path, lines: int = 20) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return [
            sanitize_text(line.rstrip(), 1000)
            for line in handle.readlines()[-max(1, min(lines, 100)) :]
        ]
