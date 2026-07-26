from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import select
import signal
import stat
import struct
import termios
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .claude import _authentication_error, _clean_environment, discover_claude
from .errors import AppError, ErrorCode
from .locks import FileLock
from .logging_utils import sanitize_text
from .paths import AppPaths

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ANSI_CURSOR_RE = re.compile(r"\x1b\[[0-9;?]*(?:A|B|E|F|G|H|J|K|f)")
_ANSI_OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)", re.DOTALL)
_ANSI_STRING_RE = re.compile(r"\x1b[P_X^].*?\x1b\\", re.DOTALL)
_ANSI_SINGLE_RE = re.compile(r"\x1b[@-_]")
_WHITESPACE_RE = re.compile(r"\s+")
_READY_PROMPT_RE = re.compile(r"(?:^|\n)\s*[❯>]\s*(?:\n|$)")
_TRUST_RE = re.compile(
    r"(?:do you trust (?:the )?(?:files|folder)|trust this (?:folder|workspace)|"
    r"yes,\s*(?:i )?trust|yes,\s*proceed)",
    re.IGNORECASE,
)
_NOT_AUTHENTICATED_RE = re.compile(
    r"(?:not logged in|please (?:log in|run /login)|authentication required|"
    r"login required|run [`']?claude auth login)",
    re.IGNORECASE,
)
_UNKNOWN_USAGE_RE = re.compile(
    r"(?:unknown (?:skill|command)\s*:?\s*/?usage|"
    r"(?:skill|command)\s+/?usage\s+(?:is )?not (?:found|available|supported))",
    re.IGNORECASE,
)
_QUOTA_RE = re.compile(
    r"\b(?:current\s+)?(?:session|week(?:ly)?|day|5\s*(?:h|hour)|five[- ]hour|"
    r"all models|sonnet only)\b",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(?<!\d)(?:100|[1-9]?\d)(?:\.\d+)?\s*%")
_RESET_RE = re.compile(
    r"\b(?:reset(?:s|ting)?|renew(?:s|al)?|refresh(?:es)?|"
    r"resets?\s+(?:at|in|on)|remaining\s+time|time\s+left)\b",
    re.IGNORECASE,
)
_PROHIBITED_USAGE_CHROME = (
    "api usage billing",
    "status config usage stats",
    "welcome to claude code",
    "do you trust the files",
    "trust this folder",
    "unknown skill: usage",
)
_REQUIRED_SAFE_FLAGS = (
    "--no-chrome",
    "--permission-mode",
    "--tools",
    "--mcp-config",
    "--strict-mcp-config",
)
_MAX_TRANSCRIPT_BYTES = 256 * 1024


class UsageSessionState(str, Enum):
    STARTING = "starting"
    TRUST_PROMPT = "trust_prompt"
    READY = "ready"
    USAGE_SENT = "usage_sent"
    RESULT = "result"
    NOT_AUTHENTICATED = "not_authenticated"
    USAGE_UNAVAILABLE = "usage_unavailable"
    PROCESS_EXITED = "process_exited"
    TIMED_OUT = "timed_out"


@dataclass(slots=True)
class _PtyProcess:
    pid: int
    descriptor: int
    returncode: int | None = None

    def read(self, timeout: float) -> str:
        if self.returncode is not None:
            return ""
        readable, _, _ = select.select([self.descriptor], [], [], max(0.0, timeout))
        if not readable:
            return ""
        try:
            chunk = os.read(self.descriptor, 65536)
        except OSError as exc:
            if exc.errno in {errno.EAGAIN, errno.EIO, errno.EWOULDBLOCK}:
                return ""
            raise
        return chunk.decode("utf-8", errors="replace")

    def write(self, value: bytes) -> None:
        pending = memoryview(value)
        while self.returncode is None and pending:
            try:
                written = os.write(self.descriptor, pending)
            except BlockingIOError:
                _, writable, _ = select.select([], [self.descriptor], [], 0.1)
                if not writable:
                    continue
            except OSError as exc:
                if exc.errno in {errno.EIO, errno.EPIPE}:
                    return
                raise
            else:
                pending = pending[written:]

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        try:
            child, status_value = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.returncode = 0
            return self.returncode
        if child == 0:
            return None
        self.returncode = os.waitstatus_to_exitcode(status_value)
        return self.returncode

    def terminate(self, grace_seconds: float = 1.0) -> None:
        if self.poll() is not None:
            return
        try:
            os.killpg(self.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + max(0.0, grace_seconds)
        while time.monotonic() < deadline:
            if self.poll() is not None:
                return
            time.sleep(0.05)
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            _, status_value = os.waitpid(self.pid, 0)
            self.returncode = os.waitstatus_to_exitcode(status_value)
        except ChildProcessError:
            self.returncode = 0

    def close(self) -> None:
        try:
            os.close(self.descriptor)
        except OSError:
            pass


def query_usage(
    paths: AppPaths,
    config: dict[str, Any],
    *,
    timeout_seconds: int = 20,
    poll_interval_seconds: float = 0.1,
) -> dict[str, Any]:
    """Read Claude subscription usage in a GUI-free, app-owned pseudo-terminal."""
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

    workspace = prepare_usage_workspace(paths)
    environment = _clean_environment(paths, config)
    with FileLock(paths.run_lock, timeout=0, error_code=ErrorCode.ALREADY_RUNNING):
        output = run_usage_session(
            capabilities.executable,
            workspace=workspace,
            help_text=capabilities.help_text,
            environment=environment,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    usage_text = extract_usage_text("", output)
    if not usage_text:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Claude Code kullanım bilgisi doğrulanamadı.",
        )
    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "usage_text": usage_text,
        "formatted_text": format_usage_message(usage_text),
    }


def prepare_usage_workspace(paths: AppPaths) -> Path:
    """Create and verify the only directory for which trust may be confirmed."""
    paths.ensure()
    expected_uid = os.getuid()
    for directory in (paths.base, paths.runtime_dir):
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise AppError(
                ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
                "Güvenli kullanım çalışma dizini doğrulanamadı.",
            )
        if info.st_uid != expected_uid:
            raise AppError(
                ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
                "Kullanım çalışma dizini mevcut kullanıcıya ait değil.",
            )

    workspace = paths.usage_workspace
    try:
        workspace.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = workspace.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != expected_uid:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Güvenli kullanım çalışma dizini doğrulanamadı.",
        )
    os.chmod(workspace, 0o700)
    info = workspace.lstat()
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Kullanım çalışma dizini izinleri güvenli değil.",
        )

    base = paths.base.resolve(strict=True)
    resolved = workspace.resolve(strict=True)
    if (
        resolved.parent != paths.runtime_dir.resolve(strict=True)
        or not resolved.is_relative_to(base)
    ):
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Kullanım çalışma dizini uygulama kökünün dışında.",
        )
    return resolved


def build_usage_argv(executable: str, help_text: str) -> list[str]:
    executable_path = Path(executable)
    if not executable_path.is_absolute():
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Claude CLI mutlak bir yoldan başlatılamadı.",
        )
    try:
        resolved = executable_path.resolve(strict=True)
    except OSError as exc:
        raise AppError(ErrorCode.CLAUDE_NOT_FOUND) from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise AppError(ErrorCode.CLAUDE_NOT_FOUND)

    missing = [flag for flag in _REQUIRED_SAFE_FLAGS if flag not in help_text]
    if missing:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Claude CLI güvenli arka plan oturumu için gerekli bayrakları desteklemiyor.",
            {"missing_flags": missing},
        )
    return [
        str(resolved),
        "--no-chrome",
        "--permission-mode",
        "dontAsk",
        "--tools",
        "",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--strict-mcp-config",
    ]


def run_usage_session(
    executable: str,
    *,
    workspace: Path,
    help_text: str,
    environment: dict[str, str],
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> str:
    """Drive one interactive Claude session through an invisible stdlib PTY."""
    argv = build_usage_argv(executable, help_text)
    safe_environment = dict(environment)
    safe_environment["TERM"] = "xterm-256color"
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_USE_FOUNDRY",
    ):
        safe_environment.pop(name, None)

    process = _spawn_pty_process(argv, safe_environment, workspace)
    state = UsageSessionState.STARTING
    transcript = ""
    trust_confirmed = False
    usage_sent = False
    result_seen_at: float | None = None
    latest_result = ""
    deadline = time.monotonic() + timeout_seconds

    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            chunk = process.read(min(max(poll_interval_seconds, 0.01), deadline - now))
            if chunk:
                transcript = (transcript + chunk)[-_MAX_TRANSCRIPT_BYTES:]
            normalized = normalize_terminal_transcript(transcript)

            if _NOT_AUTHENTICATED_RE.search(normalized):
                state = UsageSessionState.NOT_AUTHENTICATED
                raise AppError(
                    ErrorCode.CLAUDE_NOT_AUTHENTICATED,
                    "Claude abonelik oturumu açık değil. `claude auth login` çalıştırın.",
                )
            if usage_sent and _UNKNOWN_USAGE_RE.search(normalized):
                state = UsageSessionState.USAGE_UNAVAILABLE
                raise AppError(
                    ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
                    "Bu Claude Code sürümü `/usage` komutunu desteklemiyor.",
                )

            if not usage_sent:
                if _TRUST_RE.search(normalized) and not trust_confirmed:
                    state = UsageSessionState.TRUST_PROMPT
                    if not trust_prompt_is_for_workspace(normalized, workspace):
                        raise AppError(
                            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
                            "Beklenmeyen Claude çalışma dizini güven isteği reddedildi.",
                        )
                    process.write(b"\r")
                    trust_confirmed = True
                elif _READY_PROMPT_RE.search(normalized):
                    state = UsageSessionState.READY
                    process.write(b"/usage\r")
                    usage_sent = True
                    state = UsageSessionState.USAGE_SENT
            else:
                candidate = extract_usage_text("", transcript)
                if candidate:
                    if candidate != latest_result:
                        latest_result = candidate
                        result_seen_at = now
                    complete = usage_result_complete(candidate)
                    settled = result_seen_at is not None and now - result_seen_at >= 0.25
                    if complete or settled:
                        state = UsageSessionState.RESULT
                        process.write(b"\x1b")
                        closing_chunk = process.read(
                            min(0.1, max(0.0, deadline - time.monotonic()))
                        )
                        if closing_chunk:
                            transcript = (transcript + closing_chunk)[-_MAX_TRANSCRIPT_BYTES:]
                        process.write(b"/exit\r")
                        exit_deadline = min(deadline, time.monotonic() + 2.0)
                        while time.monotonic() < exit_deadline:
                            closing_chunk = process.read(
                                min(0.1, max(0.0, exit_deadline - time.monotonic()))
                            )
                            if closing_chunk:
                                transcript = (
                                    transcript + closing_chunk
                                )[-_MAX_TRANSCRIPT_BYTES:]
                            if process.poll() is not None:
                                break
                        return transcript

            returncode = process.poll()
            if returncode is not None:
                state = UsageSessionState.PROCESS_EXITED
                if latest_result:
                    return transcript
                raise AppError(
                    ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
                    "Claude Code kullanım oturumu sonuç üretmeden kapandı.",
                    {
                        "returncode": returncode,
                        "session_state": state.value,
                        "output": sanitize_text(normalized[-300:], 300),
                    },
                )

        state = UsageSessionState.TIMED_OUT
        raise AppError(
            ErrorCode.TIMEOUT,
            "Claude Code kullanım bilgisi zamanında alınamadı.",
            {"session_state": state.value},
        )
    finally:
        process.terminate()
        process.close()


def _spawn_pty_process(
    argv: list[str], environment: dict[str, str], workspace: Path
) -> _PtyProcess:
    pid, descriptor = pty.fork()
    if pid == 0:
        try:
            os.chdir(workspace)
            os.execve(argv[0], argv, environment)  # noqa: S606
        except OSError as exc:
            message = f"Claude PTY exec failed (errno={exc.errno})\n".encode()
            os.write(2, message)
            os._exit(127)
    os.set_blocking(descriptor, False)
    window_size = struct.pack("HHHH", 50, 160, 0, 0)
    fcntl.ioctl(descriptor, termios.TIOCSWINSZ, window_size)
    return _PtyProcess(pid=pid, descriptor=descriptor)


def trust_prompt_is_for_workspace(text: str, workspace: Path) -> bool:
    if not _TRUST_RE.search(text):
        return False
    expected = str(workspace.resolve(strict=True))
    absolute_paths = re.findall(r"/(?:Users|private|var|tmp)/[^\r\n│]+", text)
    displayed = [value.strip(" \t\"'`.,:;()[]{}") for value in absolute_paths]
    return not displayed or any(
        value == expected or value.startswith(expected + "/") for value in displayed
    )


def format_usage_message(text: str) -> str:
    lines = summarized_usage_lines(text)
    if not lines:
        raise AppError(
            ErrorCode.CLAUDE_USAGE_UNAVAILABLE,
            "Claude Code kullanım bilgisi doğrulanamadı.",
        )
    return "📊 Claude Kullanım Bilgisi\n" + "\n".join(f"• {line}" for line in lines)


def summarized_usage_lines(text: str) -> list[str]:
    result: list[str] = []
    for raw in cleaned_lines(text):
        collapsed = _clean_display_line(raw)
        if not collapsed or _is_prohibited_chrome(collapsed):
            continue
        if _is_usage_semantic_line(collapsed):
            result.append(collapsed)
    return _deduplicate_block(result)[:12]


def extract_usage_text(before: str, after: str) -> str:
    delta_lines = suffix_delta(cleaned_lines(before), cleaned_lines(after))
    candidate = _best_usage_block(delta_lines)
    if not candidate:
        candidate = _best_usage_block(cleaned_lines(after)[-240:])
    if not candidate:
        return ""
    return sanitize_text("\n".join(candidate), 3200)


def _best_usage_block(lines: list[str]) -> list[str]:
    semantic: list[str] = []
    for raw in lines:
        line = _clean_display_line(raw)
        if not line or _is_prohibited_chrome(line):
            continue
        if _is_usage_semantic_line(line):
            semantic.append(line)
    semantic = _collapse_adjacent_duplicates(semantic)[-80:]
    candidates: list[tuple[int, int, list[str]]] = []
    for start, line in enumerate(semantic):
        if not _QUOTA_RE.search(line):
            continue
        block: list[str] = []
        quota_labels: set[str] = set()
        for candidate in semantic[start : start + 12]:
            label = _quota_label(candidate)
            if label and label in quota_labels:
                break
            if label:
                quota_labels.add(label)
            block.append(candidate)
        block = _deduplicate_block(block)
        if _validated_usage_block(block):
            score = (
                sum(bool(_QUOTA_RE.search(item)) for item in block) * 4
                + sum(bool(_PERCENT_RE.search(item)) for item in block) * 3
                + sum(bool(_RESET_RE.search(item)) for item in block) * 3
            )
            candidates.append((score, start, block))
    if not candidates:
        return []
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _validated_usage_block(lines: list[str]) -> bool:
    combined = "\n".join(lines)
    if any(value in combined.lower() for value in _PROHIBITED_USAGE_CHROME):
        return False
    return bool(
        _QUOTA_RE.search(combined)
        and _PERCENT_RE.search(combined)
        and _RESET_RE.search(combined)
    )


def usage_result_complete(text: str) -> bool:
    lines = cleaned_lines(text)
    quota_labels = {_quota_label(line) for line in lines if _quota_label(line)}
    percentages = sum(bool(_PERCENT_RE.search(line)) for line in lines)
    resets = sum(bool(_RESET_RE.search(line)) for line in lines)
    return len(quota_labels) >= 2 and percentages >= 2 and resets >= 2


def _is_usage_semantic_line(line: str) -> bool:
    return bool(_QUOTA_RE.search(line) or _PERCENT_RE.search(line) or _RESET_RE.search(line))


def _quota_label(line: str) -> str:
    match = _QUOTA_RE.search(line)
    return _WHITESPACE_RE.sub(" ", match.group(0).lower()).strip() if match else ""


def _is_prohibited_chrome(line: str) -> bool:
    lowered = _WHITESPACE_RE.sub(" ", line).strip().lower()
    return any(value in lowered for value in _PROHIBITED_USAGE_CHROME)


def _clean_display_line(line: str) -> str:
    collapsed = _WHITESPACE_RE.sub(" ", line).strip()
    for chrome in _PROHIBITED_USAGE_CHROME:
        collapsed = re.sub(re.escape(chrome), " ", collapsed, flags=re.IGNORECASE)
    collapsed = _WHITESPACE_RE.sub(" ", collapsed).strip()
    return collapsed.strip(" \t•·*-_=│┃┆┇┊┋┌┐└┘├┤┬┴┼╭╮╯╰─━")


def _collapse_adjacent_duplicates(lines: list[str]) -> list[str]:
    result: list[str] = []
    for line in lines:
        if not result or result[-1].casefold() != line.casefold():
            result.append(line)
    return result


def _deduplicate_block(lines: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        key = line.casefold()
        if key not in seen:
            result.append(line)
            seen.add(key)
    return result


def suffix_delta(before_lines: list[str], after_lines: list[str]) -> list[str]:
    if not before_lines:
        return after_lines
    max_overlap = min(len(before_lines), len(after_lines), 200)
    for overlap in range(max_overlap, 0, -1):
        if before_lines[-overlap:] == after_lines[:overlap]:
            return after_lines[overlap:]
    common_prefix = 0
    for left, right in zip(before_lines, after_lines, strict=False):
        if left != right:
            break
        common_prefix += 1
    return after_lines[common_prefix:]


def cleaned_lines(text: str) -> list[str]:
    normalized = normalize_terminal_transcript(text)
    return [line.strip() for line in normalized.replace("\r", "\n").splitlines()]


def normalize_terminal_transcript(text: str) -> str:
    value = _ANSI_OSC_RE.sub("", text)
    value = _ANSI_STRING_RE.sub("", value)
    value = _ANSI_CURSOR_RE.sub("\n", value)
    value = _ANSI_CSI_RE.sub("", value)
    value = _ANSI_SINGLE_RE.sub("", value)
    value = value.replace("\x08", "").replace("\x00", "")
    value = "".join(char for char in value if char in "\n\r\t" or ord(char) >= 32)
    return value.replace("\r\n", "\n").replace("\r", "\n")


def strip_ansi(text: str) -> str:
    return normalize_terminal_transcript(text).rstrip("\n")
