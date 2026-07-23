from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .config import load_config
from .errors import AppError, ErrorCode
from .io_utils import atomic_write_json
from .locks import FileLock
from .logging_utils import log_event, sanitize_text
from .paths import AppPaths
from .state import update_state

SECRET_PATH_PATTERNS = (
    re.compile(r"(^|/)\.env($|\.)", re.IGNORECASE),
    re.compile(r"(^|/)(id_rsa|id_ed25519)(\.|$)", re.IGNORECASE),
    re.compile(r"\.credentials\.json$", re.IGNORECASE),
    re.compile(r"(^|/)secrets?/", re.IGNORECASE),
    re.compile(r"\.(pem|key|p12|pfx)$", re.IGNORECASE),
)
SECRET_CONTENT_PATTERNS = (
    re.compile(rb"sk-ant-[A-Za-z0-9_-]{16,}"),
    re.compile(rb"\b\d{8,12}:[A-Za-z0-9_-]{25,}\b"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
)


def _run(
    argv: list[str],
    *,
    timeout: int = 120,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            argv,
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=env,
            cwd=cwd,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppError(
            ErrorCode.DEPLOYMENT_FAILED, f"Command failed: {Path(argv[0]).name}"
        ) from exc


def _git_env(paths: AppPaths, repository_url: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "PATH", "LANG", "LC_ALL", "TMPDIR"}
    }
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    wrapper = paths.config_dir / "git-ssh-wrapper"
    if repository_url.startswith("git@"):
        if not wrapper.is_file() or not os.access(wrapper, os.X_OK):
            raise AppError(ErrorCode.GIT_AUTH_FAILED, "Secure Git SSH wrapper is not configured")
        environment["GIT_SSH"] = str(wrapper)
        environment["GIT_SSH_VARIANT"] = "ssh"
    return environment


def _validate_repository(url: str) -> None:
    if os.environ.get("CLAUDE_STARTER_ALLOW_LOCAL_GIT") == "1" and (
        url.startswith("file://") or Path(url).is_absolute()
    ):
        return
    if not re.fullmatch(r"git@github\.com:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", url):
        raise AppError(ErrorCode.CONFIG_INVALID, "Only GitHub SSH repository URLs are accepted")


class ReleaseManager:
    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.paths.ensure()

    def _deployment_config(self) -> dict[str, Any]:
        config = load_config(self.paths, create=True)["deployment"]
        if not config["enabled"]:
            raise AppError(ErrorCode.CONFIG_INVALID, "Deployment is disabled")
        url = str(config["repository_url"])
        if not url:
            raise AppError(ErrorCode.CONFIG_INVALID, "deployment.repository_url is not configured")
        _validate_repository(url)
        return config

    def _git(self, args: list[str], config: dict[str, Any], timeout: int = 120) -> str:
        git = shutil.which("git")
        if not git:
            raise AppError(ErrorCode.GIT_NOT_FOUND)
        process = _run(
            [git, *args],
            timeout=timeout,
            env=_git_env(self.paths, str(config["repository_url"])),
        )
        if process.returncode != 0:
            text = sanitize_text(process.stderr.decode("utf-8", "replace"), 400)
            if "host key verification failed" in text.lower():
                raise AppError(ErrorCode.GIT_HOST_KEY_CHANGED, text)
            if "permission denied" in text.lower():
                raise AppError(ErrorCode.GIT_AUTH_FAILED, text)
            raise AppError(ErrorCode.GIT_REPOSITORY_UNREACHABLE, text)
        return process.stdout.decode("utf-8", "replace").strip()

    def _ensure_repo(self, config: dict[str, Any]) -> None:
        if not self.paths.repo.exists():
            git = shutil.which("git")
            if not git:
                raise AppError(ErrorCode.GIT_NOT_FOUND)
            init = _run([git, "init", "--bare", str(self.paths.repo)])
            if init.returncode != 0:
                raise AppError(
                    ErrorCode.RELEASE_PREPARATION_FAILED, "Unable to create bare repository"
                )
            self._git(
                [
                    "--git-dir",
                    str(self.paths.repo),
                    "remote",
                    "add",
                    "origin",
                    config["repository_url"],
                ],
                config,
            )
        remote = self._git(
            ["--git-dir", str(self.paths.repo), "remote", "get-url", "origin"], config
        )
        if remote != config["repository_url"]:
            raise AppError(
                ErrorCode.GIT_REPOSITORY_UNREACHABLE,
                "Configured repository does not match mirror origin",
            )

    def fetch_target(self) -> tuple[dict[str, Any], str]:
        config = self._deployment_config()
        self._ensure_repo(config)
        branch = config["branch"]
        refspec = f"+refs/heads/{branch}:refs/remotes/origin/{branch}"
        self._git(
            ["--git-dir", str(self.paths.repo), "fetch", "--prune", "origin", refspec],
            config,
            timeout=300,
        )
        target = self._git(
            [
                "--git-dir",
                str(self.paths.repo),
                "rev-parse",
                "--verify",
                f"refs/remotes/origin/{branch}^{{commit}}",
            ],
            config,
        )
        if not re.fullmatch(r"[0-9a-f]{40,64}", target):
            raise AppError(ErrorCode.UNTRUSTED_COMMIT)
        tree = self._git(
            ["--git-dir", str(self.paths.repo), "ls-tree", "-r", "--full-tree", target], config
        )
        if any(line.startswith("160000 ") for line in tree.splitlines()):
            raise AppError(
                ErrorCode.UNTRUSTED_COMMIT, "Submodules are not accepted in production releases"
            )
        return config, target

    def active_manifest(self) -> dict[str, Any] | None:
        try:
            path = self.paths.current.resolve(strict=True) / "release.json"
        except (OSError, RuntimeError):
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def check(self) -> dict[str, Any]:
        config, target = self.fetch_target()
        active = self.active_manifest()
        active_sha = active.get("commit_sha") if active else None
        return {
            "update_available": active_sha != target,
            "active_commit_sha": active_sha,
            "remote_commit_sha": target,
            "short_commit_sha": target[:12],
            "branch": config["branch"],
            "commit_summary": sanitize_text(
                self._git(
                    ["--git-dir", str(self.paths.repo), "log", "-1", "--format=%s", target],
                    config,
                ),
                200,
            ),
            "ci_verification": "protected_branch_external_not_machine_verified",
        }

    def _safe_extract(self, archive: bytes, destination: Path) -> None:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as handle:
            for member in handle.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk():
                    raise AppError(ErrorCode.RELEASE_PREPARATION_FAILED, "Unsafe archive member")
                if any(pattern.search(member.name) for pattern in SECRET_PATH_PATTERNS):
                    raise AppError(
                        ErrorCode.RELEASE_PREPARATION_FAILED,
                        "Repository contains a forbidden secret path",
                    )
            # Members were rejected above if absolute, traversing, symlinked, or hard-linked.
            handle.extractall(destination)  # noqa: S202  # nosec B202
        self._scan_extracted_secrets(destination)

    def _scan_extracted_secrets(self, destination: Path) -> None:
        for path in destination.rglob("*"):
            if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
                continue
            data = path.read_bytes()
            if b"\x00" in data[:1024]:
                continue
            if any(pattern.search(data) for pattern in SECRET_CONTENT_PATTERNS):
                raise AppError(
                    ErrorCode.RELEASE_PREPARATION_FAILED,
                    f"Potential secret content found in {path.relative_to(destination)}",
                )

    def _prepare_release(self, config: dict[str, Any], target: str) -> Path:
        if shutil.disk_usage(self.paths.releases).free < 512 * 1024 * 1024:
            raise AppError(
                ErrorCode.DISK_SPACE_LOW,
                "At least 512 MiB of free space is required to stage a release",
            )
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        release = self.paths.releases / f"{timestamp}-{target[:12]}"
        release.mkdir(mode=0o700)
        archive_process = _run(
            [
                shutil.which("git") or "git",
                "--git-dir",
                str(self.paths.repo),
                "archive",
                "--format=tar",
                target,
            ],
            timeout=120,
            env=_git_env(self.paths, str(config["repository_url"])),
        )
        if archive_process.returncode != 0:
            raise AppError(ErrorCode.RELEASE_PREPARATION_FAILED, "git archive failed")
        self._safe_extract(archive_process.stdout, release)
        venv = _run([sys.executable, "-m", "venv", str(release / ".venv")], timeout=120)
        if venv.returncode != 0:
            raise AppError(
                ErrorCode.DEPENDENCY_INSTALL_FAILED, "Unable to create release virtual environment"
            )
        venv_python = release / ".venv/bin/python"
        site = _run(
            [str(venv_python), "-c", "import site; print(site.getsitepackages()[0])"],
            timeout=20,
        )
        if site.returncode != 0:
            raise AppError(
                ErrorCode.DEPENDENCY_INSTALL_FAILED,
                "Unable to inspect release virtual environment",
            )
        site_path = Path(site.stdout.decode().strip())
        (site_path / "claude_window_starter.pth").write_text(
            str(release / "backend") + "\n",
            encoding="utf-8",
        )
        self._predeploy_checks(release, venv_python)
        manifest = {
            "schema_version": 1,
            "application_version": _read_version(release),
            "commit_sha": target,
            "short_commit_sha": target[:12],
            "branch": config["branch"],
            "build_time": datetime.now(timezone.utc).isoformat(),
            "deploy_time": None,
            "python_version": _python_version(venv_python),
            "dependency_lock_hash": _lock_hash(release),
            "deploy_result": "staged",
            "health_check_result": "passed",
            "healthy": False,
        }
        atomic_write_json(release / "release.json", manifest)
        return release

    def _predeploy_checks(self, release: Path, python: Path) -> None:
        env = dict(os.environ)
        env.pop("ENABLE_LOCAL_DEPLOYMENT_TEST", None)
        env.pop("PYTHONPATH", None)
        env["CLAUDE_STARTER_HOME"] = str(self.paths.base)
        checks = [
            [str(python), "-m", "compileall", "-q", str(release / "backend")],
            [
                str(python),
                "-m",
                "unittest",
                "discover",
                "-s",
                str(release / "tests"),
                "-p",
                "test_*.py",
            ],
            [str(python), "-m", "claude_starter", "config", "validate", "--json"],
            [str(python), "-m", "claude_starter", "health", "--no-services", "--json"],
        ]
        for argv in checks:
            process = _run(argv, timeout=180, env=env, cwd=release)
            if process.returncode != 0:
                error = sanitize_text(process.stderr.decode("utf-8", "replace"), 400)
                raise AppError(ErrorCode.PRE_DEPLOY_TEST_FAILED, error or f"Failed: {argv[-1]}")
        config = load_config(self.paths, create=False)
        if config["telegram"]["enabled"]:
            telegram = _run(
                [
                    str(python),
                    "-m",
                    "claude_starter",
                    "telegram-test",
                    "--no-message",
                    "--json",
                ],
                timeout=30,
                env=env,
                cwd=release,
            )
            if telegram.returncode != 0:
                raise AppError(ErrorCode.PRE_DEPLOY_TEST_FAILED, "Telegram getMe check failed")
        analyzer = shutil.which("systemd-analyze")
        units = list((release / "systemd").glob("*.service")) + list(
            (release / "systemd").glob("*.timer")
        )
        if analyzer and units:
            process = _run([analyzer, "verify", *[str(path) for path in units]], timeout=60)
            if process.returncode != 0:
                raise AppError(ErrorCode.PRE_DEPLOY_TEST_FAILED, "systemd unit verification failed")

    def apply(self) -> dict[str, Any]:
        config = self._deployment_config()
        if not config.get("protected_branch_confirmed"):
            raise AppError(
                ErrorCode.UNTRUSTED_COMMIT,
                "Confirm GitHub protected-main required checks before production deployment",
            )
        with FileLock(
            self.paths.update_lock, timeout=0, error_code=ErrorCode.UPDATE_ALREADY_RUNNING
        ):
            with FileLock(self.paths.run_lock, timeout=130, error_code=ErrorCode.ALREADY_RUNNING):
                _, target = self.fetch_target()
                active = self.active_manifest()
                if active and active.get("commit_sha") == target:
                    raise AppError(ErrorCode.NO_UPDATE_AVAILABLE)
                release: Path | None = None
                old_current = _safe_link_target(self.paths.current, self.paths.releases)
                try:
                    release = self._prepare_release(config, target)
                    if old_current:
                        _atomic_symlink(old_current, self.paths.previous)
                    _atomic_symlink(release, self.paths.current)
                    _restart_services()
                    self._post_health(release, config)
                    manifest = json.loads((release / "release.json").read_text(encoding="utf-8"))
                    manifest.update(
                        {
                            "deploy_time": datetime.now(timezone.utc).isoformat(),
                            "deploy_result": "success",
                            "health_check_result": "passed",
                            "healthy": True,
                        }
                    )
                    atomic_write_json(release / "release.json", manifest)
                    result = {
                        "status": "success",
                        "release": release.name,
                        "commit_sha": target,
                        "rollback_performed": False,
                    }
                    self._record_deployment(result)
                    self._cleanup(config["retain_releases"])
                    return result
                except Exception as exc:
                    rolled_back = False
                    rollback_error: str | None = None
                    if old_current and config["rollback_on_failure"]:
                        try:
                            _atomic_symlink(old_current, self.paths.current)
                            _restart_services()
                            self._post_health(old_current, config)
                            rolled_back = True
                        except Exception as rollback_exc:
                            rollback_error = sanitize_text(str(rollback_exc), 300)
                            rolled_back = False
                    error_message = sanitize_text(str(exc), 300)
                    result = {
                        "status": "failed",
                        "target_commit_sha": target,
                        "rollback_performed": rolled_back,
                        "error": error_message,
                    }
                    if rollback_error:
                        result["rollback_error"] = rollback_error
                    self._record_deployment(result)
                    if rollback_error:
                        raise AppError(
                            ErrorCode.ROLLBACK_FAILED,
                            "Deployment failed and the previous release health check also failed",
                        ) from exc
                    if isinstance(exc, AppError):
                        raise
                    raise AppError(ErrorCode.DEPLOYMENT_FAILED, error_message) from exc

    def _post_health(self, release: Path, config: dict[str, Any]) -> None:
        if os.environ.get("CLAUDE_STARTER_FAULT_POST_HEALTH") == release.name:
            raise AppError(ErrorCode.HEALTH_CHECK_FAILED, "Injected post-deploy health failure")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(release / "backend")
        env["CLAUDE_STARTER_HOME"] = str(self.paths.base)
        process = _run(
            [str(release / ".venv/bin/python"), "-m", "claude_starter", "health", "--json"],
            timeout=int(config["health_check_timeout_seconds"]),
            env=env,
        )
        if process.returncode != 0:
            detail = sanitize_text(
                (process.stderr or process.stdout).decode("utf-8", "replace"),
                500,
            )
            raise AppError(
                ErrorCode.HEALTH_CHECK_FAILED,
                f"Post-deploy health check failed: {detail}",
            )

    def list_releases(self) -> list[dict[str, Any]]:
        releases = []
        for path in sorted(self.paths.releases.iterdir(), reverse=True):
            manifest = path / "release.json"
            try:
                value = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                releases.append({"release": path.name, **value})
        return releases

    def rollback(self, release_name: str | None = None) -> dict[str, Any]:
        with FileLock(
            self.paths.update_lock, timeout=0, error_code=ErrorCode.UPDATE_ALREADY_RUNNING
        ):
            target: Path | None = None
            if release_name:
                candidate = self.paths.releases / release_name
                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(self.paths.releases.resolve())
                    if resolved.is_dir():
                        target = resolved
                except (OSError, ValueError):
                    target = None
            else:
                target = _safe_link_target(self.paths.previous, self.paths.releases)
            if target is None:
                raise AppError(ErrorCode.NO_HEALTHY_PREVIOUS_RELEASE)
            try:
                manifest = json.loads((target / "release.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise AppError(ErrorCode.INVALID_RELEASE) from exc
            if not manifest.get("healthy"):
                raise AppError(ErrorCode.INVALID_RELEASE, "Target release is not marked healthy")
            old_current = _safe_link_target(self.paths.current, self.paths.releases)
            _atomic_symlink(target, self.paths.current)
            if old_current:
                _atomic_symlink(old_current, self.paths.previous)
            try:
                _restart_services()
                self._post_health(target, self._deployment_config())
            except Exception as exc:
                if old_current:
                    _atomic_symlink(old_current, self.paths.current)
                    _restart_services()
                raise AppError(ErrorCode.ROLLBACK_FAILED, "Rollback health check failed") from exc
            result = {
                "status": "rollback_success",
                "release": target.name,
                "commit_sha": manifest.get("commit_sha"),
            }
            self._record_deployment(result)
            return result

    def _record_deployment(self, result: dict[str, Any]) -> None:
        update_state(self.paths, lambda state: state.__setitem__("last_deployment", result))
        log_event(
            self.paths,
            {"trigger_source": "deployment", "deployment_status": result.get("status"), **result},
        )

    def _cleanup(self, retain: int) -> None:
        protected = {
            path.resolve()
            for path in (
                _safe_link_target(self.paths.current, self.paths.releases),
                _safe_link_target(self.paths.previous, self.paths.releases),
            )
            if path
        }
        protected.update(_running_release_paths(self.paths.releases))
        candidates = sorted(
            (path for path in self.paths.releases.iterdir() if path.is_dir()), reverse=True
        )
        for path in candidates:
            manifest = path / "release.json"
            try:
                value = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if value.get("healthy") and path.resolve() not in protected:
                protected.add(path.resolve())
                break
        kept = 0
        for path in candidates:
            if path.resolve() in protected or kept < max(1, int(retain)):
                kept += 1
                continue
            shutil.rmtree(path)


def _running_release_paths(releases: Path) -> set[Path]:
    protected: set[Path] = set()
    proc = Path("/proc")
    if not proc.is_dir():
        return protected
    releases_root = releases.resolve()
    for process in proc.iterdir():
        if not process.name.isdigit():
            continue
        for candidate in (process / "exe", process / "cwd"):
            try:
                target = candidate.resolve(strict=True)
                relative = target.relative_to(releases_root)
            except (OSError, ValueError, RuntimeError):
                continue
            if relative.parts:
                protected.add(releases_root / relative.parts[0])
    return protected


def _atomic_symlink(target: Path, link: Path) -> None:
    temporary = link.with_name(f".{link.name}.{os.getpid()}.tmp")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    os.replace(temporary, link)


def _safe_link_target(link: Path, releases: Path) -> Path | None:
    try:
        target = link.resolve(strict=True)
        target.relative_to(releases.resolve())
        return target
    except (OSError, ValueError, RuntimeError):
        return None


def _restart_services() -> None:
    systemctl = shutil.which("systemctl")
    if not systemctl or os.environ.get("CLAUDE_STARTER_SKIP_SERVICE_RESTART") == "1":
        return
    process = _run(
        [systemctl, "--user", "try-restart", "claude-window-starter-telegram.service"], timeout=30
    )
    if process.returncode != 0:
        raise AppError(ErrorCode.SERVICE_RESTART_FAILED, "Telegram service restart failed")


def _read_version(release: Path) -> str:
    init = release / "backend/claude_starter/__init__.py"
    match = re.search(r'__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"))
    return match.group(1) if match else "unknown"


def _python_version(python: Path) -> str:
    process = _run([str(python), "--version"], timeout=10)
    return (process.stdout or process.stderr).decode().strip()


def _lock_hash(release: Path) -> str | None:
    import hashlib

    path = release / "requirements-runtime.lock"
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()
