from __future__ import annotations

import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import local_now
from .errors import AppError, ErrorCode
from .locks import FileLock
from .logging_utils import log_event, sanitize_text
from .paths import AppPaths
from .state import load_state, update_state
from .usage import captured_rate_limits, next_window_time, normalized_rate_limits

WINDOW_UNVERIFIED = (
    "Claude isteği başarılı; resmi rate_limits alanı alınamadığı için sonraki çalışma "
    "başarı zamanından beş saat sonrası olarak tahmin edildi."
)
WINDOW_VERIFIED = (
    "Beş saatlik pencerenin reset zamanı Claude Code rate_limits verisiyle doğrulandı."
)

PROHIBITED_ENV = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
}


@dataclass(slots=True)
class ClaudeCapabilities:
    executable: str | None
    version: str | None
    architecture: str
    help_text: str
    auth_status: str
    auth_method: str | None
    login_command: str | None
    prohibited_credentials: list[str]

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("help_text", None)
        return value


def _run_small(
    argv: list[str], *, timeout: int = 10, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", "inspection timed out")
    except OSError:
        return subprocess.CompletedProcess(argv, 127, "", "inspection failed")


def _settings_use_api_helper() -> bool:
    config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    candidates = [config_dir / "settings.json", Path.home() / ".claude.json"]
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and _contains_key(data, "apiKeyHelper"):
            return True
    return False


def _contains_key(value: Any, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(_contains_key(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False


def prohibited_credentials() -> list[str]:
    found = sorted(name for name in PROHIBITED_ENV if os.environ.get(name))
    if _settings_use_api_helper():
        found.append("apiKeyHelper")
    return found


def discover_claude() -> ClaudeCapabilities:
    executable = shutil.which("claude")
    architecture = platform.machine().lower()
    if executable is None:
        return ClaudeCapabilities(
            None, None, architecture, "", "not_found", None, None, prohibited_credentials()
        )
    version_process = _run_small([executable, "--version"])
    help_process = _run_small([executable, "--help"])
    auth_process = _run_small([executable, "auth", "status", "--json"])
    auth_status = "unknown"
    auth_method: str | None = None
    login_command = _discover_login_command(executable)
    if auth_process.stdout.strip():
        try:
            auth = json.loads(auth_process.stdout)
            if isinstance(auth, dict):
                authenticated = auth.get("loggedIn", auth.get("authenticated"))
                auth_status = "authenticated" if authenticated is True else "not_authenticated"
                method = auth.get("authMethod", auth.get("method"))
                auth_method = str(method) if method else None
        except json.JSONDecodeError:
            auth_status = "unknown"
    elif auth_process.returncode != 0:
        auth_status = "not_authenticated"
    return ClaudeCapabilities(
        executable=executable,
        version=sanitize_text(
            version_process.stdout.strip() or version_process.stderr.strip(), 200
        ),
        architecture=architecture,
        help_text=help_process.stdout,
        auth_status=auth_status,
        auth_method=auth_method,
        login_command=login_command,
        prohibited_credentials=prohibited_credentials(),
    )


def _discover_login_command(executable: str) -> str:
    auth_login = _run_small([executable, "auth", "login", "--help"])
    if auth_login.returncode in {0, 1, 2}:
        return "claude auth login"
    direct_login = _run_small([executable, "login", "--help"])
    if direct_login.returncode in {0, 1, 2}:
        return "claude login"
    return "claude auth login"


def _clean_environment(paths: AppPaths, config: dict[str, Any]) -> dict[str, str]:
    allowed = {
        "HOME",
        "PATH",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "USER",
        "LOGNAME",
        "SHELL",
        "XDG_CONFIG_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
        "CLAUDE_CONFIG_DIR",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    # Claude Code needs USER to access macOS Keychain for subscription auth.
    # If the parent process did not forward USER, resolve it from the OS directly.
    if "USER" not in environment:
        import pwd as _pwd

        try:
            environment["USER"] = _pwd.getpwuid(os.getuid()).pw_name
        except (KeyError, AttributeError):
            pass
    if "LOGNAME" not in environment and "USER" in environment:
        environment["LOGNAME"] = environment["USER"]
    environment["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] = "1"
    return environment


def _authentication_error(
    capabilities: ClaudeCapabilities, reason: str | None = None
) -> AppError:
    login_command = capabilities.login_command or "claude auth login"
    message = (
        f"Claude subscription session is not available. Run `{login_command}` in Terminal, "
        "complete login, then retry."
    )
    if reason:
        message = f"{message} ({sanitize_text(reason, 160)})"
    return AppError(
        ErrorCode.CLAUDE_NOT_AUTHENTICATED,
        message,
        {"login_command": login_command, "auth_status": capabilities.auth_status},
    )


def _classify_failure(
    stderr: str, stdout: str, returncode: int, capabilities: ClaudeCapabilities
) -> AppError:
    text = f"{stderr}\n{stdout}".lower()
    if "model" in text and any(
        word in text for word in ("unavailable", "not available", "invalid model")
    ):
        return AppError(ErrorCode.MODEL_UNAVAILABLE, "Requested Claude model is unavailable")
    if any(
        word in text
        for word in (
            "rate limit",
            "usage limit",
            "limit reached",
            "session limit",
            "weekly limit",
        )
    ):
        return AppError(ErrorCode.RATE_OR_USAGE_LIMIT)
    if any(word in text for word in ("not logged in", "authentication", "unauthorized", "oauth")):
        return _authentication_error(capabilities, stderr or stdout)
    if any(
        word in text
        for word in (
            "network",
            "connection",
            "timed out",
            "temporary failure",
            "could not resolve",
            "dns",
        )
    ):
        return AppError(ErrorCode.NETWORK_UNAVAILABLE)
    return AppError(
        ErrorCode.NONZERO_EXIT,
        f"Claude exited with code {returncode}: {sanitize_text(stderr or stdout, 300)}",
    )


def _statusline_settings(paths: AppPaths) -> str:
    python = shlex.quote(str(Path(sys.executable).resolve()))
    home = shlex.quote(str(paths.base))
    command = f"{python} -m claude_starter.statusline_capture --home {home}"
    return json.dumps({"statusLine": {"type": "command", "command": command}})


def _build_args(
    capabilities: ClaudeCapabilities,
    model: str | None,
    paths: AppPaths | None = None,
) -> list[str]:
    if capabilities.executable is None:
        raise AppError(ErrorCode.CLAUDE_NOT_FOUND)
    help_text = capabilities.help_text
    argv = [capabilities.executable, "-p", "--output-format", "json"]
    if model:
        argv.extend(["--model", model])
    optional_flags = (
        ("--no-session-persistence", ["--no-session-persistence"]),
        ("--no-chrome", ["--no-chrome"]),
        ("--disable-slash-commands", ["--disable-slash-commands"]),
    )
    for marker, values in optional_flags:
        if marker in help_text:
            argv.extend(values)
    if "--permission-mode" in help_text and "dontAsk" in help_text:
        argv.extend(["--permission-mode", "dontAsk"])
    if "--tools" in help_text:
        argv.extend(["--tools", ""])
    if "--setting-sources" in help_text:
        argv.extend(["--setting-sources", ""])
    if paths is not None and "--settings" in help_text:
        argv.extend(["--settings", _statusline_settings(paths)])
    if "--mcp-config" in help_text and "--strict-mcp-config" in help_text:
        argv.extend(["--mcp-config", '{"mcpServers":{}}', "--strict-mcp-config"])
    return argv


def _invoke_once(
    paths: AppPaths,
    config: dict[str, Any],
    capabilities: ClaudeCapabilities,
    model: str | None,
) -> dict[str, Any]:
    argv = _build_args(capabilities, model, paths)
    environment = _clean_environment(paths, config)
    started = time.monotonic()
    started_epoch = time.time()
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        env=environment,
        cwd=paths.runtime_dir,
    )
    try:
        stdout, stderr = process.communicate(config["prompt"], timeout=config["timeout_seconds"])
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise AppError(ErrorCode.TIMEOUT, "Claude request timed out") from exc
    duration = round(time.monotonic() - started, 3)
    if process.returncode != 0:
        raise _classify_failure(stderr, stdout, process.returncode or 1, capabilities)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AppError(ErrorCode.NONZERO_EXIT, "Claude returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.NONZERO_EXIT, "Claude JSON result is not an object")
    result = payload.get("result")
    if not isinstance(result, str) or not result.strip():
        raise AppError(ErrorCode.EMPTY_RESPONSE)
    actual_model = payload.get("model")
    if not actual_model and isinstance(payload.get("modelUsage"), dict):
        actual_model = next(iter(payload["modelUsage"]), None)
    rate_limits = normalized_rate_limits(payload.get("rate_limits"))
    if rate_limits is None and "--settings" in capabilities.help_text:
        # Claude can render its status line immediately after the print-mode
        # process exits. Give that bounded helper a moment to atomically publish
        # the structured reset timestamp.
        deadline = time.monotonic() + 2
        while rate_limits is None and time.monotonic() < deadline:
            rate_limits = captured_rate_limits(paths, newer_than=started_epoch)
            if rate_limits is None:
                time.sleep(0.05)
    return {
        "response": sanitize_text(result.strip(), 1000),
        "selected_model": str(actual_model or model or "default"),
        "duration_seconds": duration,
        "exit_code": process.returncode,
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
        "rate_limits": rate_limits,
    }


def run_claude(
    paths: AppPaths, config: dict[str, Any], *, trigger: str, dry_run: bool
) -> dict[str, Any]:
    paths.ensure()
    capabilities = discover_claude()
    if capabilities.executable is None:
        raise AppError(ErrorCode.CLAUDE_NOT_FOUND)
    if capabilities.prohibited_credentials:
        raise AppError(
            ErrorCode.API_KEY_DETECTED,
            "Disallowed API/provider credentials detected; real execution stopped",
            {"sources": capabilities.prohibited_credentials},
        )
    if capabilities.auth_status == "not_authenticated":
        raise _authentication_error(capabilities)
    now = local_now(config)
    is_automatic = trigger in {"automatic", "catch_up", "background"}
    if is_automatic and not config["enabled"]:
        raise AppError(ErrorCode.CONFIG_INVALID, "Automatic execution is disabled")
    state = load_state(paths)
    next_window = state.get("next_window_run_at")
    if is_automatic and isinstance(next_window, str):
        try:
            if datetime.now(timezone.utc) < datetime.fromisoformat(next_window):
                raise AppError(ErrorCode.WINDOW_NOT_DUE)
        except ValueError:
            pass
    if dry_run:
        return {
            "dry_run": True,
            "trigger": trigger,
            "claude": capabilities.public_dict(),
            "would_use_model": config["model"],
            "real_request_sent": False,
        }
    with FileLock(paths.run_lock, timeout=0, error_code=ErrorCode.ALREADY_RUNNING):
        state = load_state(paths)
        next_window = state.get("next_window_run_at")
        if is_automatic and isinstance(next_window, str):
            try:
                if datetime.now(timezone.utc) < datetime.fromisoformat(next_window):
                    raise AppError(ErrorCode.WINDOW_NOT_DUE)
            except ValueError:
                pass
        selected = config["model"]
        candidates: list[str | None]
        if selected == "auto":
            cache = state.get("model_cache")
            cached = None
            if isinstance(cache, dict) and cache.get("cli_version") == capabilities.version:
                cached = cache.get("model")
                if cached == "default":
                    cached = None
            candidates = []
            ordered_candidates: tuple[str | None, ...] = (
                (cached, "haiku", None) if cached is not None else ("haiku", None)
            )
            for candidate in ordered_candidates:
                if candidate not in candidates:
                    candidates.append(candidate)
        else:
            candidates = [str(selected)]
        result: dict[str, Any] | None = None
        last_error: AppError | None = None
        for candidate in candidates:
            try:
                result = _invoke_once(paths, config, capabilities, candidate)
                break
            except AppError as exc:
                last_error = exc
                if exc.code != ErrorCode.MODEL_UNAVAILABLE or candidate is None:
                    raise
        if result is None:
            raise last_error or AppError(ErrorCode.NONZERO_EXIT)
        completed_at = datetime.now(timezone.utc)
        ended = completed_at.isoformat()
        next_at, verified_window = next_window_time(
            result.get("rate_limits"),
            completed_at=completed_at,
            grace_seconds=int(config["reset_grace_seconds"]),
        )
        record = {
            "trigger_source": trigger,
            "run_type": "automatic" if is_automatic else "manual",
            "end_time": ended,
            "status": "success",
            "selected_model": result["selected_model"],
            "claude_cli_version": capabilities.version,
            "exit_code": 0,
            "response_summary": result["response"],
            "usage_window_verification": {
                "verified": verified_window,
                "method": "claude_statusline" if verified_window else "five_hour_estimate",
                "message": WINDOW_VERIFIED if verified_window else WINDOW_UNVERIFIED,
            },
            "rate_limits": result.get("rate_limits"),
            "next_window_run_at": next_at.isoformat(),
        }

        def save_run(current: dict[str, Any]) -> None:
            current["last_run"] = record
            current["automatic_blocked"] = None
            current["automatic_blocked_date"] = None
            if is_automatic:
                current["last_automatic_date"] = now.date().isoformat()
            current["usage_window"] = {
                "verified": verified_window,
                "source": "claude_statusline" if verified_window else "five_hour_estimate",
                "rate_limits": result.get("rate_limits"),
                "captured_at": ended,
            }
            current["next_window_run_at"] = next_at.isoformat()
            if selected == "auto":
                current["model_cache"] = {
                    "model": result["selected_model"]
                    if result["selected_model"] != "default"
                    else "default",
                    "cli_version": capabilities.version,
                }

        update_state(paths, save_run)
        log_event(paths, record)
        return {
            **result,
            "real_request_sent": True,
            "usage_window_verification": record["usage_window_verification"],
        }
