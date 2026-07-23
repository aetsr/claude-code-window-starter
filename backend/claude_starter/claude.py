from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
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

WINDOW_UNVERIFIED = (
    "Gerçek Claude isteği başarıyla gönderildi ancak 5 saatlik kullanım "
    "penceresinin başladığı teknik olarak doğrulanamadı."
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
    prohibited_credentials: list[str]

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value.pop("help_text", None)
        return value


def _run_small(argv: list[str], *, timeout: int = 10, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
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
        return ClaudeCapabilities(None, None, architecture, "", "not_found", None, prohibited_credentials())
    version_process = _run_small([executable, "--version"])
    help_process = _run_small([executable, "--help"])
    auth_process = _run_small([executable, "auth", "status", "--json"])
    auth_status = "unknown"
    auth_method: str | None = None
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
        version=sanitize_text(version_process.stdout.strip() or version_process.stderr.strip(), 200),
        architecture=architecture,
        help_text=help_process.stdout,
        auth_status=auth_status,
        auth_method=auth_method,
        prohibited_credentials=prohibited_credentials(),
    )


def _credential_path(paths: AppPaths, name: str) -> Path | None:
    credential_directory = os.environ.get("CREDENTIALS_DIRECTORY")
    candidates = []
    if credential_directory:
        candidates.append(Path(credential_directory) / name)
    candidates.append(paths.secrets_dir / name)
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_mode & 0o077 == 0:
                return candidate
        except OSError:
            continue
    return None


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
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment["CLAUDE_CODE_SKIP_PROMPT_HISTORY"] = "1"
    if config.get("execution_mode") == "oracle":
        token_path = _credential_path(paths, "claude_oauth_token")
        if token_path is None:
            raise AppError(ErrorCode.CLAUDE_NOT_AUTHENTICATED, "OAuth systemd credential is missing")
        token = token_path.read_text(encoding="utf-8").strip()
        if not token:
            raise AppError(ErrorCode.CLAUDE_NOT_AUTHENTICATED, "OAuth systemd credential is empty")
        environment["CLAUDE_CODE_OAUTH_TOKEN"] = token
    return environment


def _classify_failure(stderr: str, stdout: str, returncode: int) -> AppError:
    text = f"{stderr}\n{stdout}".lower()
    if "model" in text and any(word in text for word in ("unavailable", "not available", "invalid model")):
        return AppError(ErrorCode.MODEL_UNAVAILABLE, "Requested Claude model is unavailable")
    if any(word in text for word in ("rate limit", "usage limit", "limit reached")):
        return AppError(ErrorCode.RATE_OR_USAGE_LIMIT)
    if any(word in text for word in ("not logged in", "authentication", "unauthorized", "oauth")):
        return AppError(ErrorCode.CLAUDE_NOT_AUTHENTICATED)
    return AppError(
        ErrorCode.NONZERO_EXIT,
        f"Claude exited with code {returncode}: {sanitize_text(stderr or stdout, 300)}",
    )


def _build_args(capabilities: ClaudeCapabilities, model: str | None) -> list[str]:
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
        raise _classify_failure(stderr, stdout, process.returncode or 1)
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
    return {
        "response": sanitize_text(result.strip(), 1000),
        "selected_model": str(actual_model or model or "default"),
        "duration_seconds": duration,
        "exit_code": process.returncode,
        "usage": payload.get("usage") if isinstance(payload.get("usage"), dict) else None,
    }


def run_claude(paths: AppPaths, config: dict[str, Any], *, trigger: str, dry_run: bool) -> dict[str, Any]:
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
    now = local_now(config)
    is_automatic = trigger in {"automatic", "catch_up"}
    if is_automatic and not config["enabled"]:
        raise AppError(ErrorCode.CONFIG_INVALID, "Automatic execution is disabled")
    state = load_state(paths)
    if (
        is_automatic
        and config["prevent_duplicate_daily_run"]
        and state.get("last_automatic_date") == now.date().isoformat()
    ):
        raise AppError(ErrorCode.ALREADY_RAN_TODAY)
    if dry_run:
        return {
            "dry_run": True,
            "trigger": trigger,
            "claude": capabilities.public_dict(),
            "would_use_model": config["model"],
            "real_request_sent": False,
        }
    with FileLock(paths.run_lock, timeout=0, error_code=ErrorCode.ALREADY_RUNNING):
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
            ordered_candidates: tuple[str | None, ...] = ((cached, "haiku", None) if cached is not None else ("haiku", None))
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
        ended = datetime.now(timezone.utc).isoformat()
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
                "verified": False,
                "method": "unsupported",
                "message": WINDOW_UNVERIFIED,
            },
        }

        def save_run(current: dict[str, Any]) -> None:
            current["last_run"] = record
            if is_automatic:
                current["last_automatic_date"] = now.date().isoformat()
            if selected == "auto":
                current["model_cache"] = {
                    "model": result["selected_model"] if result["selected_model"] != "default" else "default",
                    "cli_version": capabilities.version,
                }

        update_state(paths, save_run)
        log_event(paths, record)
        return {**result, "real_request_sent": True, "usage_window_verification": record["usage_window_verification"]}
