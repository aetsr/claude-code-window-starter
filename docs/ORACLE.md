# Oracle Ubuntu installation

Before mutation, run `scripts/diagnose-server.sh` or manually collect `uname -m`, `lscpu`, `free -h`, `/etc/os-release`, and `df -h`. Only ARM64/AArch64 and x86_64 are accepted. Python 3.10+ and systemd are required; the installer does not add a third-party Python PPA.

The root bootstrap prints these facts, verifies Anthropic’s APT signing-key fingerprint, installs Claude Code from the official stable repository if absent, creates the locked `claude-starter` user, enables lingering, and stages a release. It may run from a Git checkout or from a `git archive` transfer when the matching commit SHA is supplied as its first argument. Daily execution and Telegram run as user services, not root.

Default base path:

```text
/var/lib/claude-starter/.local/share/claude-window-starter/
  repo.git/
  releases/
  current -> releases/...
  previous -> releases/...
  shared/{config,secrets,state,logs,runtime}/
```

The installer enables only the daily timer; application config remains disabled, so no Claude request occurs. Configure OAuth, run a dry-run, review health, and only then enable automation. On uninstall, `--yes` preserves shared data; `--purge` explicitly removes it.

User services require `XDG_RUNTIME_DIR=/run/user/$(id -u claude-starter)` when managed through `sudo -u claude-starter`. Oracle’s `ubuntu` account normally has sudo, but the installer stops if non-interactive privilege is unavailable.
