<div align="center">

# Claude Window Starter

**macOS app for scheduling Claude API usage windows — with a Telegram bot, atomic releases, and zero runtime dependencies.**

[![CI](https://github.com/aetsr/claude-window-starter/actions/workflows/ci.yml/badge.svg)](https://github.com/aetsr/claude-window-starter/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%E2%80%93%203.13-blue?logo=python&logoColor=white)](https://www.python.org)
[![macOS](https://img.shields.io/badge/macOS-13%2B-black?logo=apple&logoColor=white)](https://www.apple.com/macos/)
[![Swift](https://img.shields.io/badge/swift-5.9%2B-orange?logo=swift&logoColor=white)](https://swift.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)

</div>

---

## What it does

Claude Window Starter runs a single scheduled Claude Code subscription request on macOS, respecting your 5-hour usage windows. It ships as a native Swift menu-bar app backed by a pure-stdlib Python agent.

- **Window scheduling** — 5-hour and weekly windows with automatic anchor calibration
- **Telegram bot** — full remote control: run, calibrate, set prompt, manage users, get notifications
- **Background mode** — prevents idle sleep, monitors network, retries missed windows on reconnect
- **Atomic releases** — every install is immutable; rollback to any healthy local release in one command
- **Zero runtime deps** — backend runs on Python stdlib only; no pip install at runtime

---

## Requirements

- macOS 13 Ventura or later (Apple Silicon & Intel)
- Python 3.10 – 3.13 (system or Homebrew)
- Xcode 15+ (to build the Swift app)
- A Claude Code subscription

---

## Installation

```bash
# 1. Build backend + Swift app
scripts/build-local.sh

# 2. Install to /Applications + register LaunchAgents
scripts/install-macos.sh

# 3. Open the app
open "/Applications/Claude Window Starter.app"
```

The installer places the backend under `~/Library/Application Support/ClaudeWindowStarter`, installs the app to `/Applications`, and registers launchd helpers. All config, state, and logs stay outside Git. Telegram tokens are stored exclusively in Keychain.

**Uninstall:**
```bash
scripts/uninstall-macos.sh          # keeps config/state/logs
scripts/uninstall-macos.sh --purge  # removes everything
```

---

## Telegram Bot

1. Create a bot via [@BotFather](https://t.me/BotFather) and copy the token
2. Open the app → **Telegram** tab → paste token into the secure field
3. Add your numeric user ID and chat ID to the allowlists
4. Start the service — the bot registers its command menu automatically

### Available commands

| Category | Commands |
|----------|----------|
| **Status** | `/status` `/usage` `/schedule` `/health` `/diagnose` `/logs` |
| **Automation** | `/run` `/dryrun` `/automation_on` `/automation_off` |
| **Sleep** | `/sleep_on` `/sleep_off` |
| **Calibration** | `/calibrate_5h HH:MM` `/calibrate_weekly YYYY-MM-DD HH:MM` |
| **Settings** | `/setmodel` `/setprompt` `/settimezone` |
| **Users** | `/users` `/adduser <id>` `/removeuser <id>` |

`/usage` opens a short-lived, app-managed macOS Terminal window, starts Claude Code with the discovered absolute CLI path, runs `/usage`, then closes only that window. It does not need an open Claude terminal tab, but the service account needs macOS Automation permission to control Terminal.

All destructive actions (`/run`, `/setprompt`) require an inline confirmation tied to the originating user and chat. Polling offset is written atomically; a file lock prevents duplicate bot instances.

---

## CLI

```bash
python3 -m claude_starter --home <dir> --json <command> [args]
```

| Command | Description |
|---------|-------------|
| `status` | System status and window info |
| `usage` | Read `/usage` in a temporary, app-managed Terminal window |
| `run` | Execute Claude with the configured prompt |
| `calibrate` | Set window anchor (`--window-type five_hour\|weekly --anchor ISO`) |
| `config` | Read / patch config (`get`, `set`, `patch-stdin`) |
| `schedule` | Advance windows, record network state |
| `health` | Health report |
| `telegram-bot` | Start the Telegram polling bot |
| `service` | Manage launchd services (`start`, `stop`, `restart`) |
| `releases` | List local releases |
| `rollback` | Roll back to a previous healthy release |

All commands emit a versioned JSON envelope: `{"ok": true, "status": "...", ...}`.

---

## Atomic Releases & Rollback

Each `install-macos.sh` run creates an immutable release directory with its own manifest and health result. The `current` symlink is only updated when the new release passes its health check.

```bash
scripts/list-releases.sh     # list available releases
scripts/rollback.sh          # roll back to previous healthy release
```

Up to 5 releases are kept by default.

---

## Background Mode

When **Background Mode** is enabled:

- An `IOPMAssertion` prevents idle system sleep
- Network transitions are monitored via `SCNetworkReachability`
- If a window was missed while offline, it runs once on reconnect
- `calibration_needed` is set automatically when windows are missed

> Lid-close sleep on MacBooks is enforced by macOS and cannot be prevented without an external display connected.

---

## Security

- Telegram token → macOS Keychain (never written to disk or config)
- Claude runs in a restricted environment (no shell, controlled PATH)
- All log output is sanitized before writing (API keys, tokens redacted)
- CI runs `bandit`, `ruff`, `mypy`, and a custom `security_scan.py` on every push
- Config, state, and runtime files are gitignored

See [SECURITY.md](SECURITY.md) for the full security model.

---

## Development

```bash
# Run tests (Python 3.10+)
python3 -m pytest tests/ -v

# Lint + type-check
ruff check backend/
mypy backend/

# Security scan
python3 scripts/security_scan.py

# Dry run (no real Claude request)
scripts/dry-run.sh
```

---

## Documentation

- [macOS Setup](docs/MACOS.md)
- [Telegram Bot](docs/TELEGRAM.md)
- [Local Releases](docs/LOCAL_RELEASES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
