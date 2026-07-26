from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

from .claude import _authentication_error, discover_claude
from .errors import AppError, ErrorCode
from .locks import FileLock
from .logging_utils import sanitize_text
from .paths import AppPaths

_ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
_WHITESPACE_RE = re.compile(r"\s+")
_SEPARATOR_RE = re.compile(r"^[\s\-\u2500-\u257f]+$")
_READY_RE = re.compile(r"(?:welcome to claude|claude code|/help|/status)", re.IGNORECASE)
_KEYWORDS = (
    "usage", "limit", "remaining", "reset", "session", "weekly", "daily", "5h", "hours", "minutes", "%",
)
_PROHIBITED_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
)


def query_usage(
    paths: AppPaths,
    config: dict[str, Any],
    *,
    timeout_seconds: int = 20,
    poll_interval_seconds: float = 0.5,
) -> dict[str, Any]:
    """Read subscription usage from an app-owned, temporary Terminal window."""
    del config  # Authentication remains in the user's Claude Code configuration.
    capabilities = discover_claude()
    if capabilities.executable is None:
        raise AppError(ErrorCode.CLAUDE_NOT_FOUND)
    if capabilities.prohibited_credentials:
        raise AppError(
            ErrorCode.API_KEY_DETECTED,
            "Disallowed API/provider credentials detected; usage query stopped",
            {"sources": capabilities.prohibited_credentials},
        )
    if capabilities.auth_status == "not_authenticated":
        raise _authentication_error(capabilities)

    with FileLock(paths.run_lock, timeout=0, error_code=ErrorCode.ALREADY_RUNNING):
        output = run_usage_session(
            capabilities.executable,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    usage_text = extract_usage_text("", output)
    if not usage_text:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Claude Code kullanım bilgisi alınamadı. Lütfen tekrar deneyin.",
        )
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "usage_text": usage_text,
        "formatted_text": format_usage_message(usage_text),
    }


def run_usage_session(
    executable: str,
    *,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> str:
    """Create, operate, and always close one dedicated Terminal window."""
    window_id: int | None = None
    try:
        window_id = create_usage_terminal_window(executable)
        before = wait_for_interactive_start(
            window_id,
            timeout_seconds=min(10, timeout_seconds),
            poll_interval_seconds=poll_interval_seconds,
        )
        send_usage_command(window_id)
        return read_usage_output(
            window_id,
            before,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
    finally:
        if window_id is not None:
            close_usage_terminal_window(window_id)


def create_usage_terminal_window(executable: str) -> int:
    """Open a new minimized Terminal window and return its stable window id."""
    command = usage_launch_command(executable)
    script = [
        'tell application "Terminal"',
        f"set usageTab to (do script {applescript_string(command)})",
        "set usageWindow to first window whose selected tab is usageTab",
        "set usageWindowId to id of usageWindow",
        "set miniaturized of usageWindow to true",
        "return usageWindowId as text",
        "end tell",
    ]
    raw = run_osascript(script).strip()
    try:
        return int(raw)
    except ValueError as exc:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Geçici Terminal penceresi oluşturulamadı.",
        ) from exc


def usage_launch_command(executable: str) -> str:
    """Build a shell command that cannot inherit provider API credentials."""
    unset = " ".join(f"-u {name}" for name in _PROHIBITED_ENV)
    return f"exec /usr/bin/env {unset} -- {shlex.quote(executable)} --no-chrome"


def wait_for_interactive_start(
    window_id: int,
    *,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_contents = ""
    while time.monotonic() < deadline:
        last_contents = terminal_window_contents(window_id)
        if _READY_RE.search(strip_ansi(last_contents)):
            return last_contents
        time.sleep(poll_interval_seconds)
    raise AppError(
        ErrorCode.TIMEOUT,
        "Claude Code geçici Terminal penceresinde hazır hale gelmedi.",
    )


def send_usage_command(window_id: int) -> None:
    run_osascript([
        'tell application "Terminal"',
        f'do script "/usage" in selected tab of window id {window_id}',
        "end tell",
    ])


def read_usage_output(
    window_id: int,
    before: str,
    *,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    latest = before
    stable_polls = 0
    while time.monotonic() < deadline:
        time.sleep(poll_interval_seconds)
        latest = terminal_window_contents(window_id)
        usage = extract_usage_text(before, latest)
        if usage:
            if latest == before:
                stable_polls = 0
            else:
                stable_polls += 1
            if stable_polls >= 2:
                return latest
        else:
            stable_polls = 0
    if extract_usage_text(before, latest):
        return latest
    raise AppError(ErrorCode.TIMEOUT, "Claude Code kullanım bilgisi zamanında alınamadı.")


def terminal_window_contents(window_id: int) -> str:
    return run_osascript([
        'tell application "Terminal"',
        f"return contents of selected tab of window id {window_id}",
        "end tell",
    ])


def close_usage_terminal_window(window_id: int) -> None:
    """Close only the window created by this request; cleanup must not mask errors."""
    try:
        run_osascript([
            'tell application "Terminal"',
            f"if exists window id {window_id} then close window id {window_id}",
            "end tell",
        ])
    except AppError:
        pass


def run_osascript(lines: list[str]) -> str:
    """Run a Terminal-only AppleScript and translate Automation failures."""
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", "\n".join(lines)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError(ErrorCode.TIMEOUT, "Terminal otomasyonu zaman aşımına uğradı.") from exc
    except OSError as exc:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "macOS Terminal otomasyonu başlatılamadı.",
        ) from exc
    if result.returncode:
        detail = sanitize_text(result.stderr or result.stdout, 300)
        message = "macOS Terminal Automation izni gerekli veya Terminal erişilemedi."
        raise AppError(ErrorCode.CLAUDE_USAGE_UNAVAILABLE, message, {"automation_error": detail})
    return result.stdout


def applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


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
        if any(keyword in lower for keyword in _KEYWORDS):
            result.append(collapsed)
        elif result:
            result.append(collapsed)
        if len(result) >= 8:
            break
    return result or [
        line for line in cleaned_lines(text)
        if "/usage" not in line.lower() and not _SEPARATOR_RE.match(line)
    ][:8]


def extract_usage_text(before: str, after: str) -> str:
    delta_lines = suffix_delta(cleaned_lines(before), cleaned_lines(after))
    candidate_lines = usage_candidate_lines(delta_lines)
    if not candidate_lines:
        candidate_lines = usage_candidate_lines(cleaned_lines(after)[-80:])
    return sanitize_text("\n".join(candidate_lines).strip(), 3200) if candidate_lines else ""


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
        if any(keyword in line.lower() for keyword in _KEYWORDS):
            return cleaned[index : index + 10]
    return []


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
    return _ANSI_RE.sub("", text).replace("\x08", "")
