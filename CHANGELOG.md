# Changelog

All notable changes to Claude Window Starter are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Discoverability and release preparation
- Position the README around Claude Code five-hour window scheduling and legitimate early requests.
- Document actual dependencies, cache behavior, installation/rollback limitations, and non-bypass/affiliation disclaimers.
- Add launch copy, screenshot guidance, discoverability audit, release notes template and a draft artifact workflow.
- Correct Swift toolchain instructions and remove stale test/version badges.
- Repair existing Python lint/format failures without changing scheduling or credential behavior.
- Correct CLI/Telegram subscription terminology and test the installed wheel without a source-tree PYTHONPATH override.

The changes below were previously labeled 2.2.0 (2026-08-26), but package,
backend and app versions remain 2.1.0 and no GitHub Release was found during
the 2026-09-05 audit. They remain unreleased pending version reconciliation.

### Added
- **OAuth Usage API** — queries `api.anthropic.com/api/oauth/usage`, with CLI PTY fallback when unavailable
- OAuth token auto-discovery from macOS Keychain (`Claude Code-credentials`)
- Usage result caching (300 s) to avoid redundant API calls
- Dual timezone display — primary Europe/Berlin with secondary Europe/Istanbul (e.g. `21:10 DE / 22:10 TR`)

### Changed
- Default timezone switched from Europe/Istanbul to Europe/Berlin
- `query_usage()` now tries: cache → OAuth API → PTY fallback (was PTY-only)
- Usage API uses `curl` subprocess to bypass Python SSL certificate issues on macOS
- README rewritten with architecture diagram, feature table, and project structure

### Fixed
- "Şimdi Senkronize Et" (Sync Now) can use the OAuth path before PTY fallback; latency depends on cache/network/service availability
- PTY startup fallback timer increased from 3 s to 6 s for trust dialog edge cases
- Telegram bot messages now show both DE and TR times

## 2.1.0 — 2026-08-26

### Added
- Adaptive weekday busy-hours planner with default `08:00–17:00` maximum-quota strategy
- Structured five-hour/weekly `/usage` parsing with source, capture time, and freshness state
- Locked, idempotent `schedule --tick` evaluation and fixed tool-free Haiku `anchor` path
- macOS busy-time controls, daily preview, observed reset/source display, sync, and manual override
- Telegram `/workhours`, `/sync_usage`, and enriched `/schedule` commands
- Deduplicated anchor, manual-window, weekly-limit, and persistent-failure notifications

### Changed
- Config/state and CLI envelope schemas are v4; v3 installs migrate to manual mode without enabling automation
- Swift background helper delegates all time and quota decisions to the Python scheduler
- Offline/wake behavior expires stale anchors instead of replaying missed work
- Version advanced to 2.1.0 across Python, wheel scripts, and the macOS bundle

### Fixed
- Claude Code prompts containing a rotating suggestion are recognized before issuing `/usage`; a bounded three-second PTY startup fallback prevents false query timeouts
- Telegram long-poll socket expiry is treated as an empty poll with a wider HTTP deadline, preventing repeated timeout/backoff loops
- `/sync_usage` now returns the same concise, user-facing usage errors as `/usage`

### Removed
- Obsolete Linux systemd verification from the macOS-only CI workflow

## 2.0.0 — 2026-07-26

### Added
- Window-based scheduling architecture (five_hour + weekly windows) with `windows.py`
- PTY-based `/usage` command — reads Claude subscription usage in an invisible app-owned pseudo-terminal
- macOS native menu-bar app with SwiftUI (calibration UI, Telegram pairing, background toggle)
- Background supervisor with `IOPMAssertion` (prevents idle sleep), `NWPathMonitor` (network transitions)
- Atomic release system with symlink-based rollback (`current`/`previous`)
- Telegram bot with full command menu, user/chat allowlist, confirmation nonces
- Callback query handling for inline confirmation buttons
- `/pair` flow for one-command Telegram user/chat authorization
- Multi-user support (comma-separated user and chat IDs)
- `calibration_needed` detection on missed windows after network reconnect
- `telegram-user` CLI subcommands (add, remove, list)
- `config patch-stdin` for atomic backend configuration updates
- `schedule --network-state` for offline/online connectivity tracking
- Security scanning in CI (`bandit`, `ruff`, `mypy`, custom `security_scan.py`)
- Production-ready test suite (173+ tests)

### Changed
- Architecture simplified from v1 automation modes to window-based scheduling
- Schema updated to v3 (removed v1/v2 fields from config and state)
- Telegram responses changed from JSON/raw to human-readable Turkish messages
- UI simplified to 2 tabs (Configuration + Maintenance)
- All Turkish strings internationalized to English across backend, Swift app, and docs
- README rewritten with badges, tables, and full feature documentation
- License added (Apache 2.0)

### Fixed
- Calibration persistence: settings save no longer wipes `anchor_iso`
- Telegram authorization: private chat check fixed for `/adduser` users
- Multi-user `/pair` now appends to lists instead of replacing
- Z-suffix ISO 8601 strings from Swift accepted everywhere (`fromisoformat` → `_parse_iso`)
- Markdown escape for special characters in dynamic bot responses
- Health check accepts `schema_version` 3 (was hardcoded to v2)
- PTY cleanup: non-blocking reaping prevents lock hangs
- Telegram supervisor handoff race condition closed

### Removed
- `deployment.py` (server-side deployment module) — project is macOS-only
- `statusline_capture.py` — replaced by `usage.py` PTY approach
- `test_deployment.py`, `test_schedulers.py` — corresponding test removals
- v1/v2 config fields (`schedule_time`, `automation_mode`, `reset_grace_seconds`, etc.)
- `dist/` intermediate build directory
- Pre-2.0 single-job launchd agent

## 1.0.0 — 2026-07-23

### Added
- Initial release: basic Claude Code subscription request scheduler
- macOS launchd integration
- Telegram bot with basic command support
- Atomic release switching

[Unreleased]: https://github.com/aetsr/claude-window-starter/commits/main
