# Claude Window Starter

A macOS menu bar app that pre-starts and schedules Claude Code's 5-hour usage window around your working hours. It tracks 5-hour and weekly usage with reset countdowns, replans around observed active windows, and optionally provides Telegram remote control. If you want your Claude Code usage window to reset at a more useful time, scheduling a small early request can help — this app automates that.

It does **not** increase quota, bypass Anthropic usage limits, reset server-side limits, or exploit authentication. Scheduled requests consume normal subscription usage. An already active window cannot be moved; Anthropic determines whether a request starts a new window and when it resets.

[![CI](https://github.com/aetsr/claude-code-window-starter/actions/workflows/ci.yml/badge.svg)](https://github.com/aetsr/claude-code-window-starter/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

<!-- Real screenshot TODO: capture the Automation tab with planner, observed
reset, source/freshness and next action. See docs/SCREENSHOTS.md. Insert a real,
reviewed capture here using a stable relative path. -->

Illustrative default plan, not a screenshot or a promise of server reset times:

```text
05:00             08:00        10:03         15:06        17:00
early request     work starts  next request next request work ends
                  Observed resets can change this plan.
```

## Installation

### Recommended installation today: from source

There is currently no published, ready-to-install macOS download. The installer builds the app and installs its backend and launchd helpers in one command. A standalone `.app` build is not a complete installation. See [release readiness](docs/RELEASING.md).

Requirements:

- macOS 13+; builds target the host architecture (Apple Silicon or Intel).
- Python 3.10+ with `venv`; CI covers 3.10–3.13. Python remains a runtime requirement. There are no third-party Python runtime packages.
- Swift 6.0+ and a macOS SDK for building, such as Xcode 16+ or compatible Command Line Tools. Your chosen toolchain may require a newer build host than macOS 13. Check `swift --version`.
- [Claude Code](https://code.claude.com/docs/en/setup) installed and signed in with subscription access. No Anthropic API key is required. Network access is needed for Claude and optional Telegram.
- Standard macOS utilities including `curl`, `security`, `codesign`, and `launchctl`.

```bash
git clone https://github.com/aetsr/claude-code-window-starter.git
cd claude-code-window-starter
claude auth login
./scripts/install-macos.sh
```

Run from a clean checkout: the installer refuses uncommitted source changes. It builds and opens `/Applications/Claude Window Starter.app`, creates a virtual environment under `~/Library/Application Support/ClaudeWindowStarter`, and registers user LaunchAgents. Writing to `/Applications` may require permission. Swift/Xcode is needed for source installation and upgrades, not normal operation afterward.

### Build from source without installing

```bash
./scripts/build-local.sh
```

This runs Python/Swift tests, builds and installs a wheel in a temporary environment, checks plists, and creates `dist/Claude Window Starter.app`. It needs pip/build dependency access. To build only the Swift bundle, use `./scripts/build-macos-app.sh dist`. These artifact builds do not install the backend or services.

Without an output argument, `build-macos-app.sh` instead replaces the installed app, syncs Python files into the active backend, and launches it. Use that mode only intentionally for development.

## Quick start

1. Open the app and choose your IANA timezone, such as `Europe/Berlin`.
2. In **Automation**, set and save your adaptive work hours (Work start / Work end). Defaults are weekdays, 08:00–17:00.
3. Click **Sync now** to inspect usage and observed reset. Reads may reuse a cache for up to five minutes.
4. Review today's planned requests, then enable **Automation**. Optional **Sleep prevention** requests that macOS keep the machine running; actual sleep still prevents execution.
5. Keep the Mac online at the planned times. The launchd helper runs independently of the menu window.

New installs disable automation, sleep prevention, and Telegram. Upgrades preserve existing preferences and can resume previously enabled automation.

## Why this exists

Starting your first Claude Code request when work begins can put a useful reset later in the day. This app schedules a small early request and shows what the server reports so you can plan around the window. Timing helps organize access; it does not create extra quota.

## Features

- Work-hours-aware scheduling, daily request preview, and manual calibration fallback.
- Five-hour and weekly usage percentages when available, reset information, and local countdowns.
- Replanning around an observed active window and suppression when weekly exhaustion is observed.
- macOS menu bar interface, background helper, and network monitoring.
- Missed-action expiration after sleep/offline periods without replaying a backlog.
- Optional Telegram status, usage sync, settings, and confirmed manual requests.
- Local configuration/logs and Keychain storage for the Telegram token.

## How the 5-hour window scheduling works

An **anchor** is a scheduled request intended to begin normal subscription usage, not a server-side reset command.

1. The planner starts three hours before your work period, never before local midnight. For 08:00–17:00, the initial plan is 05:00, 10:03, and 15:06 (default interval: 303 minutes).
2. At a due action it queries usage: cache up to 300 seconds old → Claude Code OAuth usage endpoint using the existing Keychain credential → interactive CLI `/usage` through an app-owned invisible PTY if needed.
3. If an active five-hour window is observed, it skips the redundant request and replans from the reported reset plus the default 180-second grace period. Observed weekly exhaustion also suppresses the request.
4. Otherwise it sends a fixed Haiku request: `Reply with exactly OK. Do not use tools.` It uses the logged-in Claude Code CLI with tools disabled and no model fallback. This consumes quota.
5. Locked decisions and recorded results prevent duplicate actions. Requests more than five minutes late under default settings expire; later eligible actions remain available.

If usage measurement fails, scheduling can proceed with estimated confidence. A successful request is not independent proof of a new server window: check a subsequent observation. The OAuth endpoint and CLI output can change; instantaneous reads and exact reset alignment are not guaranteed.

## Usage and Telegram control

After installation, `./scripts/dry-run.sh` checks the request path without sending a real request. `./scripts/run-now.sh` sends your configured model/prompt; adaptive anchors always use fixed Haiku requests.

Telegram is optional. Create a bot with [BotFather](https://t.me/BotFather), save its token in the **Telegram** tab, and complete the displayed pairing flow or configure numeric private user/chat allowlists. See [setup](docs/TELEGRAM.md).

| Purpose | Commands |
| --- | --- |
| Inspect | `/status`, `/usage`, `/sync_usage`, `/schedule`, `/health`, `/diagnose`, `/logs` |
| Run/control | `/run` (confirmation), `/dryrun`, `/automation_on`, `/automation_off` |
| Work schedule | `/workhours 08:00 17:00` |
| Sleep prevention | `/sleep_on`, `/sleep_off` |
| Calibration | `/calibrate_5h HH:MM`, `/calibrate_weekly YYYY-MM-DD HH:MM` |
| Settings | `/setmodel`, `/setprompt` (confirmation), `/settimezone` |
| Access | `/users`, `/adduser <id>`, `/removeuser <id>` |

Calibration changes local scheduling, not server limits. `/sync_usage` uses the same cache-aware query as `/usage`.

## Why not just use a cron job?

A cron job or simple Claude warmup script can send one request at a fixed time. This app adds a workday plan, observed-window replanning, quota visibility, duplicate-action protection, missed-action expiration, a menu interface, and optional remote control. It exposes measurement failures and estimated timing. It still depends on a running, connected Mac and valid Claude Code authentication.

## FAQ

### What is Claude Code's 5-hour usage window?

A time-based subscription usage allowance, separate from weekly limits. Anthropic controls the rules, which can vary by plan; see [its usage explanation](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work). This app reads reported usage and schedules ordinary requests around it.

### Can I start Claude Code's 5-hour window before I begin working?

The app can schedule a legitimate request before work, which may start an eligible window. It cannot start a second window while one is active or guarantee your preferred reset time.

### Is this a Claude Code warmup tool?

Yes, in the sense of scheduling an early request to start usage. Warmup does not mean keeping a model loaded or making responses faster.

### Does this reset or bypass Claude's usage limits?

No. It tracks the Claude Code usage reset and schedules requests. It cannot increase quota, bypass limits, manipulate authentication, or reset the server timer.

### Can it track Claude Code weekly usage?

Yes, when supplied by the usage response. Percentages and reset information appear in usage output. Manual weekly calibration is separate and cannot replenish the weekly allowance.

### Does it work when my Mac sleeps?

Requests cannot run during actual sleep. Power assertions request sleep prevention; lid-close and system policies can still suspend execution. After wake/reconnect, stale actions expire instead of firing together. This is not a wake alarm or cloud scheduler.

### Does it require the Anthropic API?

No paid API key or API billing setup is required. Requests use your Claude Code subscription. Usage inspection contacts Anthropic's OAuth usage endpoint, with a CLI `/usage` fallback. "Claude API usage windows" would confuse subscription limits with API rate limits.

## Upgrade and uninstall

From a clean checkout, run `git pull --ff-only`, then `./scripts/install-macos.sh`. Back up local config/state first; automation preferences are preserved.

```bash
./scripts/list-releases.sh
./scripts/rollback.sh --yes  # review the list first; changes backend symlinks
./scripts/uninstall-macos.sh  # preserves config/state/logs
```

Rollback is not a complete app/service downgrade. The shell installer switches backend symlinks before building the app and has no automatic health-gated rollback. See [local release limitations](docs/LOCAL_RELEASES.md). Use `./scripts/uninstall-macos.sh --purge` only to deliberately remove local app data too.

## Security & privacy

Claude execution uses an allowlisted environment, no shell, no tools, timeouts, and subscription credential checks. Telegram uses private user/chat allowlists and confirmation nonces for execution/prompt changes, with outbound long polling and no inbound port. Its Keychain token has broad local access to tolerate ad-hoc re-signing.

Usage inspection reads the existing Claude Code OAuth credential. The current `curl` call passes its bearer header as a process argument: a known local credential-exposure concern before a broad binary launch. Usage results are cached locally. No analytics service is included. See [security details](SECURITY.md).

This is an independent open-source project and is not affiliated with or endorsed by Anthropic.

## Development and tests

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.lock
PYTHONPATH=backend python3 -m unittest discover -s tests -p 'test_*.py'
swift test --package-path macos-app
ruff format --check backend tests scripts/security_scan.py
ruff check backend tests scripts/security_scan.py
mypy backend/claude_starter
bandit -q -lll -r backend
python3 scripts/security_scan.py
```

CI is the source of test status; no fixed test-count badge is maintained. For source-tree CLI inspection use `PYTHONPATH=backend python3 -m claude_starter --help`. Installation does not add a global CLI to PATH; scripts invoke the installed virtual environment directly.

## Architecture and documentation

SwiftUI calls the local Python JSON CLI. A Swift launchd helper drives `schedule --tick` and monitors connectivity; another supervises Telegram. Python owns planning, usage queries, configuration, locks, and state. Installed paths and identifiers retain **Claude Window Starter** for compatibility.

- [macOS details](docs/MACOS.md), [Telegram](docs/TELEGRAM.md), [troubleshooting](docs/TROUBLESHOOTING.md)
- [Local releases](docs/LOCAL_RELEASES.md), [release preparation](docs/RELEASING.md)
- [Discoverability audit](docs/DISCOVERABILITY.md), [launch copy](docs/LAUNCH.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Reproducible usage parsing, reset, and sleep/wake reports are useful; remove credentials and personal identifiers.

## License

[Apache License 2.0](LICENSE).
