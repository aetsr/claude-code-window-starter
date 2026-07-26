from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .errors import AppError, ErrorCode
from .logging_utils import sanitize_text

_FIELD_SEPARATOR = "\x1f"
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_WHITESPACE_RE = re.compile(r"\s+")
_SEPARATOR_RE = re.compile(r"^[\s\-\u2500-\u257f]+$")
_SUPPORTED_APPS = {
    "Terminal": "terminal",
    "iTerm": "iterm",
    "iTerm2": "iterm",
}
_KEYWORDS = (
    "usage",
    "limit",
    "remaining",
    "reset",
    "session",
    "weekly",
    "daily",
    "5h",
    "hours",
    "minutes",
    "%",
)


@dataclass(slots=True)
class SessionSnapshot:
    app_name: str
    tty: str
    title: str
    contents: str


def query_active_session_usage(
    *, timeout_seconds: int = 12, poll_interval_seconds: float = 0.5
) -> dict[str, Any]:
    snapshot = active_session_snapshot()
    if not tty_has_claude(snapshot.tty):
        raise AppError(
            ErrorCode.CLAUDE_SESSION_UNAVAILABLE,
            "Aktif Claude Code oturumu bulunamadı. Claude'u Terminal veya iTerm2'de açıp o sekmeyi öne alın.",
        )

    before = strip_ansi(snapshot.contents)
    send_usage_command(snapshot.app_name)

    deadline = time.monotonic() + timeout_seconds
    last_after = before
    stable_polls = 0
    while time.monotonic() < deadline:
        time.sleep(poll_interval_seconds)
        current = active_session_snapshot(expected_app=snapshot.app_name)
        if normalize_tty(current.tty) != normalize_tty(snapshot.tty):
            raise AppError(
                ErrorCode.CLAUDE_SESSION_UNAVAILABLE,
                "Aktif Claude Code oturumu değişti. Aynı sekmeyi açık tutup tekrar deneyin.",
            )
        current_after = strip_ansi(current.contents)
        if current_after != last_after:
            last_after = current_after
            stable_polls = 0
        elif current_after != before:
            stable_polls += 1
        if last_after != before:
            extracted = extract_usage_text(before, last_after)
            if extracted and stable_polls >= 1:
                return {
                    "app_name": current.app_name,
                    "tty": current.tty,
                    "title": current.title,
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                    "usage_text": extracted,
                    "formatted_text": format_usage_message(extracted),
                }
        else:
            stable_polls = 0

    extracted = extract_usage_text(before, last_after)
    if extracted:
        return {
            "app_name": snapshot.app_name,
            "tty": snapshot.tty,
            "title": snapshot.title,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "usage_text": extracted,
            "formatted_text": format_usage_message(extracted),
        }
    raise AppError(
        ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
        "Claude Code /usage çıktısı okunamadı. Oturum açık ve hazır durumdayken tekrar deneyin.",
    )


def format_usage_message(text: str) -> str:
    lines = summarized_usage_lines(text)
    if not lines:
        cleaned = sanitize_text(text.strip(), 3200)
        return f"📊 *Claude Kullanım Bilgisi*\n{cleaned}"
    return "📊 *Claude Kullanım Bilgisi*\n" + "\n".join(f"• {line}" for line in lines)


def summarized_usage_lines(text: str) -> list[str]:
    result: list[str] = []
    for raw in cleaned_lines(text):
        lower_raw = raw.lower()
        if "/usage" in lower_raw or _SEPARATOR_RE.match(raw):
            continue
        collapsed = _WHITESPACE_RE.sub(" ", raw).strip("•- ")
        lower = collapsed.lower()
        if not collapsed or lower == "status config usage stats":
            continue
        if not collapsed:
            continue
        if any(keyword in lower for keyword in _KEYWORDS):
            result.append(collapsed)
        elif result:
            result.append(collapsed)
        if len(result) >= 8:
            break
    if result:
        return result
    fallback = [
        line
        for line in cleaned_lines(text)
        if "/usage" not in line.lower()
        and not _SEPARATOR_RE.match(line)
        and _WHITESPACE_RE.sub(" ", line).strip().lower() != "status config usage stats"
    ]
    return fallback[:8]


def extract_usage_text(before: str, after: str) -> str:
    delta_lines = suffix_delta(cleaned_lines(before), cleaned_lines(after))
    candidate_lines = usage_candidate_lines(delta_lines)
    if not candidate_lines:
        candidate_lines = usage_candidate_lines(cleaned_lines(after)[-40:])
    if not candidate_lines:
        return ""
    text = "\n".join(candidate_lines).strip()
    return sanitize_text(text, 3200)


def usage_candidate_lines(lines: list[str]) -> list[str]:
    cleaned = []
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()
        if not stripped or "/usage" in lowered or _SEPARATOR_RE.match(stripped):
            continue
        if _WHITESPACE_RE.sub(" ", stripped).strip().lower() == "status config usage stats":
            continue
        cleaned.append(stripped)
    for index, line in enumerate(cleaned):
        lower = line.lower()
        if any(keyword in lower for keyword in _KEYWORDS):
            return cleaned[index : index + 10]
    return cleaned[:10] if cleaned else []


def suffix_delta(before_lines: list[str], after_lines: list[str]) -> list[str]:
    if not before_lines:
        return after_lines
    max_overlap = min(len(before_lines), len(after_lines), 200)
    for overlap in range(max_overlap, 0, -1):
        if before_lines[-overlap:] == after_lines[:overlap]:
            return after_lines[overlap:]
    common_prefix = 0
    for left, right in zip(before_lines, after_lines):
        if left != right:
            break
        common_prefix += 1
    return after_lines[common_prefix:]


def cleaned_lines(text: str) -> list[str]:
    return [line.strip() for line in strip_ansi(text).replace("\r", "\n").splitlines()]


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def active_session_snapshot(expected_app: str | None = None) -> SessionSnapshot:
    app_name = frontmost_terminal_app()
    if expected_app is not None and app_name != expected_app:
        raise AppError(
            ErrorCode.CLAUDE_SESSION_UNAVAILABLE,
            "Aktif terminal sekmesi değişti. Claude Code oturumunu tekrar öne alıp deneyin.",
        )
    script = terminal_snapshot_script(app_name)
    raw = run_osascript(script)
    tty, title, contents = parse_snapshot_payload(raw)
    return SessionSnapshot(app_name=app_name, tty=tty, title=title, contents=contents)


def frontmost_terminal_app() -> str:
    raw = run_osascript(
        ['tell application "System Events" to get name of first application process whose frontmost is true']
    ).strip()
    if raw not in _SUPPORTED_APPS:
        raise AppError(
            ErrorCode.CLAUDE_SESSION_UNAVAILABLE,
            "Aktif Claude Code oturumu bulunamadı. Terminal veya iTerm2 sekmesini öne alın.",
        )
    return raw


def terminal_snapshot_script(app_name: str) -> list[str]:
    if _SUPPORTED_APPS.get(app_name) == "terminal":
        return [
            'tell application "Terminal"',
            "set ttyValue to tty of selected tab of front window",
            "set titleValue to custom title of front window",
            "set contentsValue to contents of selected tab of front window",
            f'return ttyValue & "{_FIELD_SEPARATOR}" & titleValue & "{_FIELD_SEPARATOR}" & contentsValue',
            "end tell",
        ]
    return [
        f'tell application "{app_name}"',
        "set ttyValue to tty of current session of current window",
        "set titleValue to name of current session of current window",
        "set contentsValue to contents of current session of current window",
        f'return ttyValue & "{_FIELD_SEPARATOR}" & titleValue & "{_FIELD_SEPARATOR}" & contentsValue',
        "end tell",
    ]


def send_usage_command(app_name: str) -> None:
    if _SUPPORTED_APPS.get(app_name) == "terminal":
        run_osascript(
            ['tell application "Terminal" to do script "/usage" in selected tab of front window']
        )
        return
    run_osascript(
        [f'tell application "{app_name}" to tell current session of current window to write text "/usage"']
    )


def tty_has_claude(tty: str) -> bool:
    tty_name = normalize_tty(tty)
    if not tty_name:
        return False
    try:
        result = subprocess.run(
            ["ps", "-t", tty_name, "-o", "comm="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    commands = [line.strip().lower() for line in result.stdout.splitlines() if line.strip()]
    return any(command.endswith("/claude") or command == "claude" for command in commands)


def normalize_tty(tty: str) -> str:
    value = tty.strip()
    if value.startswith("/dev/"):
        value = value[5:]
    return value


def parse_snapshot_payload(raw: str) -> tuple[str, str, str]:
    parts = raw.split(_FIELD_SEPARATOR, 2)
    if len(parts) != 3:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Aktif terminal oturumunun içeriği okunamadı.",
        )
    return parts[0].strip(), parts[1].strip(), parts[2]


def run_osascript(lines: list[str]) -> str:
    argv = ["osascript"]
    for line in lines:
        argv.extend(["-e", line])
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Terminal otomasyonu zaman aşımına uğradı.",
        ) from exc
    except OSError as exc:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "macOS terminal otomasyonu başlatılamadı.",
        ) from exc
    if result.returncode != 0:
        message = sanitize_text(result.stderr or result.stdout or "osascript failed", 240)
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            f"Terminal oturumuna erişilemedi. macOS Automation iznini kontrol edin. ({message})",
        )
    return result.stdout
