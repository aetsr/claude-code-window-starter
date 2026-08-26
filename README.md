<div align="center">

# Claude Window Starter

**macOS menu bar app that maximizes your Claude Code subscription quota — with a Telegram bot, live usage tracking, and zero runtime dependencies.**

[![CI](https://github.com/aetsr/claude-window-starter/actions/workflows/ci.yml/badge.svg)](https://github.com/aetsr/claude-window-starter/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%E2%80%93%203.13-blue?logo=python&logoColor=white)](https://www.python.org)
[![macOS](https://img.shields.io/badge/macOS-13%2B-black?logo=apple&logoColor=white)](https://www.apple.com/macos/)
[![Swift](https://img.shields.io/badge/swift-5.9%2B-orange?logo=swift&logoColor=white)](https://swift.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000)](https://github.com/astral-sh/ruff)
[![Last commit](https://img.shields.io/github/last-commit/aetsr/claude-window-starter)](https://github.com/aetsr/claude-window-starter/commits/main)

</div>

---

## Overview

Claude Window Starter automatically manages your Claude Code subscription's 5-hour and weekly quota windows so you get the most out of your plan during working hours.

```
┌──────────────────────────────────────────────────────────┐
│  Claude Window Starter                            DE/TR  │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  5h Oturum   ████████░░░░░░░░░░░░  12%                  │
│  Haftalık    ████████████░░░░░░░░  59%                  │
│                                                          │
│  Sıfırlanma: 26.08 21:09 DE / 22:09 TR                 │
│                                                          │
│  ● Telegram Bot: Running                                 │
│  ● Background:   Active                                  │
│  ● Network:      Online                                  │
│                                                          │
│  [Şimdi Senkronize Et]  [Automation: ON]                │
└──────────────────────────────────────────────────────────┘
```

### Key Features

| Feature | Description |
|---------|-------------|
| **Live Usage Tracking** | Reads quota directly from Anthropic's OAuth API — instant, reliable, no PTY hacks |
| **Adaptive Scheduling** | Plans window-opening anchors around your work hours and real server resets |
| **Telegram Bot** | Full control from your phone: sync usage, run prompts, change settings |
| **Dual Timezone** | Configurable primary timezone (Europe/Berlin) with secondary display (Europe/Istanbul) |
| **Background Mode** | Keeps Mac awake on AC power, monitors network, replans after wake |
| **Atomic Releases** | Every install is immutable; one-command rollback to any healthy release |
| **Zero Runtime Deps** | Python stdlib only — no pip install at runtime |
| **Keychain Security** | Telegram token stored in macOS Keychain, survives app re-signing |

---

## How It Works

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   SwiftUI App   │────▶│  Python Backend   │────▶│  Claude Code CLI │
│  (menu bar)     │     │  (stdlib only)    │     │  (subscription)  │
└─────────────────┘     └──────────────────┘     └──────────────────┘
        │                       │                         │
        │                       ▼                         │
        │               ┌──────────────────┐              │
        │               │  OAuth Usage API  │◀─────────────┘
        │               │  (direct query)   │
        │               └──────────────────┘
        │                       │
        ▼                       ▼
┌─────────────────┐     ┌──────────────────┐
│  Telegram Bot   │     │   launchd Jobs   │
│  (long-poll)    │     │  (background +   │
│                 │     │   supervisor)    │
└─────────────────┘     └──────────────────┘
```

1. **Usage Sync** — Queries Anthropic's OAuth API directly using the Claude Code Keychain credential. Returns 5-hour and weekly quota percentages with reset times in under 1 second.

2. **Adaptive Planner** — Given your work hours (e.g. 08:00–17:00 Mon–Fri), computes optimal anchor points for each 5-hour window. Server-observed resets override the plan when they differ.

3. **Background Service** — A launchd-managed Swift agent prevents idle sleep, watches for network changes, and calls the backend scheduler every 5 seconds. Missed windows during sleep/offline are flagged for recalibration.

4. **Telegram Supervisor** — A separate launchd job runs the Telegram long-polling bot with `flock()`-based single-instance enforcement. The supervisor detects token availability, manages the worker process lifecycle, and writes real-time status to a shared JSON file.

---

## Requirements

- macOS 13 Ventura or later (Apple Silicon & Intel)
- Python 3.10 – 3.13 (system or Homebrew)
- Xcode 15+ (to build the Swift app)
- A Claude Code subscription (Pro or Max)

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
2. Open the app &rarr; **Telegram** tab &rarr; paste token into the secure field
3. Click **Pair** and follow the instructions
4. The bot starts automatically via launchd

### Commands

| Category | Commands |
|----------|----------|
| **Status** | `/status` `/usage` `/sync_usage` `/schedule` `/health` `/diagnose` `/logs` |
| **Automation** | `/run` `/dryrun` `/automation_on` `/automation_off` |
| **Sleep** | `/sleep_on` `/sleep_off` |
| **Planning** | `/workhours HH:MM HH:MM` `/calibrate_5h HH:MM` `/calibrate_weekly YYYY-MM-DD HH:MM` |
| **Settings** | `/setmodel` `/setprompt` `/settimezone` |
| **Users** | `/users` `/adduser <id>` `/removeuser <id>` |

**Usage sync**: `/usage` and `/sync_usage` query the Anthropic OAuth API using the Claude Code Keychain credential to fetch real-time 5-hour and weekly quota percentages. Falls back to an invisible PTY session if the OAuth token is unavailable.

All destructive actions (`/run`, `/setprompt`) require an inline confirmation tied to the originating user and chat.

---

## CLI

```bash
python3 -m claude_starter --home <dir> --json <command> [args]
```

| Command | Description |
|---------|-------------|
| `status` | System status and window info |
| `usage` | Read quota via OAuth API (PTY fallback) |
| `run` | Execute Claude with the configured prompt |
| `calibrate` | Set window anchor (`--window-type five_hour\|weekly --anchor ISO`) |
| `config` | Read / patch config (`get`, `set`, `patch-stdin`) |
| `schedule` | Show the adaptive plan; `--tick` is the background decision entry point |
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

- An `IOPMAssertion` prevents idle system sleep (AC power)
- Network transitions are monitored via `NWPathMonitor`
- The helper calls only the locked, idempotent `schedule --tick` backend decision
- Missed actions are expired; after wake/reconnect the remaining day is replanned
- Weekly exhaustion and persistent observation/anchor failures are deduplicated notifications

> Lid-close sleep on MacBooks is enforced by macOS and cannot be prevented without an external display connected.

---

## Security

- Telegram token stored in macOS Keychain with permissive ACL (survives ad-hoc re-signing)
- Claude runs in a restricted environment (no shell, controlled PATH, prohibited credentials stripped)
- OAuth token read from Keychain is used only for the usage API — never written to disk
- All log output is sanitized before writing (API keys, tokens redacted)
- CI runs `bandit`, `ruff`, `mypy`, and a custom `security_scan.py` on every push
- Config, state, and runtime files are gitignored
- File locks (`flock()`) prevent duplicate bot/supervisor processes

See [SECURITY.md](SECURITY.md) for the full security model.

---

## Development

```bash
# Run tests (Python 3.10+, 244 tests)
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

## Project Structure

```
claude-window-starter/
├── backend/claude_starter/    # Python backend (stdlib only)
│   ├── cli.py                 # CLI entry point
│   ├── claude.py              # Claude Code discovery & invocation
│   ├── usage.py               # OAuth API + PTY usage tracking
│   ├── scheduler.py           # Adaptive window planner
│   ├── telegram_bot.py        # Telegram long-polling bot
│   ├── config.py              # Config management (v1→v4 migration)
│   ├── state.py               # Atomic state persistence
│   ├── health.py              # Health checks & diagnostics
│   └── releases.py            # Atomic release management
├── macos-app/                 # Swift/SwiftUI menu bar app
│   ├── Sources/ClaudeWindowStarter/
│   └── Sources/ClaudeWindowStarterAgent/
├── scripts/                   # Build, install, uninstall scripts
├── tests/                     # 244 unit tests
└── docs/                      # Additional documentation
```

---

## Documentation

- [macOS Setup](docs/MACOS.md)
- [Telegram Bot](docs/TELEGRAM.md)
- [Local Releases](docs/LOCAL_RELEASES.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

---

## License

Apache 2.0 — see [LICENSE](LICENSE)
