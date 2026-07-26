"""Claude process invocation and capabilities discovery."""

from __future__ import annotations

import json
import os
import platform
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
    """Check for prohibited API credentials in environment."""
    found = []
    for key in PROHIBITED_ENV:
        if os.environ.get(key):
            found.append(key)
    if _settings_use_api_helper():
        found.append("settings.json:apiKeyHelper")
    return found


def discover_claude() -> ClaudeCapabilities:
    """Discover Claude CLI binary and its capabilities."""
    executable = None
    for dirname in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(dirname) / "claude"
        if candidate.exists() and candidate.is_file():
            executable = str(candidate)
            break

    architecture = platform.machine()
    version: str | None = None
    help_text = ""
    auth_status = "unknown"
    auth_method: str | None = None
    login_command: str | None = None

    if executable:
        result = _run_small([executable, "--version"])
        version = result.stdout.strip() if result.returncode == 0 else None

        result = _run_small([executable, "--help"])
        help_text = result.stdout if result.returncode == 0 else ""

        result = _run_small([executable, "auth", "status", "--json"], timeout=5)
        try:
            auth_data = json.loads(result.stdout)
            authenticated = auth_data.get("loggedIn", auth_data.get("authenticated"))
            if authenticated is True:
                auth_status = "authenticated"
            elif authenticated is False:
                auth_status = "not_authenticated"
            auth_method = auth_data.get("authMethod", auth_data.get("method"))
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass

        if auth_status != "authenticated":
            login_command = "claude auth login"
            result = _run_small([executable, "auth", "login", "--help"], timeout=2)
            if result.returncode == 0 and "--keyring" in result.stdout:
                login_command = "claude auth login --keyring"

    prohibited = prohibited_credentials()

    return ClaudeCapabilities(
        executable=executable,
        version=version,
        architecture=architecture,
        help_text=help_text,
        auth_status=auth_status,
        auth_method=auth_method,
        login_command=login_command,
        prohibited_credentials=prohibited,
    )


def _clean_environment(paths: AppPaths, config: dict[str, Any]) -> dict[str, str]:
    """Create a clean environment for Claude subprocess.

    Removes prohibited credentials and sets up essential variables.
    """
    import pwd

    environment = {
        "HOME": str(Path.home()),
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "en_US.UTF-8",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
    }

    # Try to get USER from environment, fall back to pwd
    if "USER" in os.environ:
        environment["USER"] = os.environ["USER"]
    else:
        try:
            environment["USER"] = pwd.getpwuid(os.getuid()).pw_name
        except (KeyError, OSError):
            pass

    if "LOGNAME" in os.environ:
        environment["LOGNAME"] = os.environ["LOGNAME"]

    if "SHELL" in os.environ:
        environment["SHELL"] = os.environ["SHELL"]

    return environment


def _authentication_error(
    capabilities: ClaudeCapabilities, stderr: str = "", stdout: str = ""
) -> AppError:
    """Format authentication error message."""
    login_command = capabilities.login_command or "claude auth login"
    reason = stderr or stdout
    message = f"Claude authentication required: {login_command}"
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
    """Classify a Claude process failure into an error code.

    Rate-limit detection is removed: windows are now determined from user-provided
    anchor times, not from Claude's JSON rate_limits output.
    """
    text = f"{stderr}\n{stdout}".lower()

    # Check for model unavailability
    if "model" in text and any(
        word in text for word in ("unavailable", "not available", "invalid model")
    ):
        return AppError(ErrorCode.MODEL_UNAVAILABLE, "Requested Claude model is unavailable")

    # Check for authentication errors
    if any(word in text for word in ("not logged in", "authentication", "unauthorized", "oauth")):
        return _authentication_error(capabilities, stderr or stdout)

    # Check for network errors
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

    # Fallback: unknown error
    return AppError(
        ErrorCode.NONZERO_EXIT,
        f"Claude exited with code {returncode}: {sanitize_text(stderr or stdout, 300)}",
    )


def _build_args(
    capabilities: ClaudeCapabilities,
    model: str | None,
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
    if "--mcp-config" in help_text and "--strict-mcp-config" in help_text:
        argv.extend(["--mcp-config", '{"mcpServers":{}}', "--strict-mcp-config"])
    return argv


def _invoke_once(
    paths: AppPaths,
    config: dict[str, Any],
    capabilities: ClaudeCapabilities,
    model: str | None,
) -> dict[str, Any]:
    argv = _build_args(capabilities, model)
    environment = _clean_environment(paths, config)
    started = time.monotonic()
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
        # If Claude CLI returned error JSON (e.g. is_error:true), extract result for classification.
        classify_text = stderr
        if not classify_text and stdout.strip().startswith("{"):
            try:
                payload = json.loads(stdout)
                if isinstance(payload, dict) and payload.get("is_error"):
                    result = str(payload.get("result", ""))
                    if result:
                        classify_text = f"{classify_text}\n{result}".strip()
            except json.JSONDecodeError:
                pass
        raise _classify_failure(classify_text or stderr, stdout, process.returncode or 1, capabilities)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AppError(ErrorCode.NONZERO_EXIT, "Claude returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise AppError(ErrorCode.NONZERO_EXIT, "Claude JSON result is not an object")
    response_value = payload.get("result")
    if not isinstance(response_value, str) or not response_value.strip():
        raise AppError(ErrorCode.EMPTY_RESPONSE)
    actual_model: Any = payload.get("model")
    if not actual_model and isinstance(payload.get("modelUsage"), dict):
        actual_model = next(iter(payload["modelUsage"]), None)
    return {
        "response": sanitize_text(response_value.strip(), 1000),
        "selected_model": str(actual_model or model or "default"),
        "duration_seconds": duration,
        "exit_code": process.returncode,
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
    }


def run_claude(
    paths: AppPaths, config: dict[str, Any], *, trigger: str, window_type: str | None = None, dry_run: bool
) -> dict[str, Any]:
    """Run Claude with the given configuration.

    Args:
        paths: Application paths
        config: Configuration dict
        trigger: Trigger type (manual, automatic, etc.)
        window_type: Window type being triggered ("five_hour", "weekly", or None)
        dry_run: If True, don't actually invoke Claude

    Returns:
        Result dict with response, model, etc.
    """
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
    if dry_run:
        return {
            "dry_run": True,
            "trigger": trigger,
            "claude": capabilities.public_dict(),
            "would_use_model": config["model"],
            "real_request_sent": False,
        }

    if capabilities.auth_status == "not_authenticated":
        raise _authentication_error(capabilities)

    with FileLock(paths.run_lock, timeout=0, error_code=ErrorCode.ALREADY_RUNNING):
        state = load_state(paths)
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
        record = {
            "trigger_source": trigger,
            "window_type": window_type,
            "end_time": completed_at.isoformat(),
            "status": "success",
            "selected_model": result["selected_model"],
            "claude_cli_version": capabilities.version,
            "exit_code": 0,
            "response_summary": result["response"],
        }

        def save_run(current: dict[str, Any]) -> None:
            current["last_run"] = record
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
        }
