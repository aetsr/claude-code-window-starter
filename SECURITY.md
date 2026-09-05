# Security model

## Secrets

The Telegram token is written to the macOS Keychain via SecureField/stdin. The token is never written to config, state, argv, environment, logs, or a release. The launchd helper reads the token from Keychain and passes it to the bot process via anonymous stdin.

Claude execution runs with `shell=False`, prompt via stdin, an allowlisted environment, an empty tool set, session persistence disabled, capability-gated flags, and a timeout. If prohibited API/provider variables are detected, the real call is aborted.

Subscription usage inspection runs in a separate, invisible stdlib PTY rooted at an app-owned `0700` workspace. It uses an absolute Claude CLI path, an allowlisted environment, no tools, `dontAsk` permission mode, Chrome disabled, and a strict empty MCP configuration. A workspace trust prompt is confirmed only for that verified directory. No Terminal/iTerm process, AppleScript, or Terminal Automation permission is used. Claude subscription login remains a manual `claude auth login` step.

## OAuth usage inspection and known limitations

Usage queries first check a local cache (up to 300 seconds), then read the existing `Claude Code-credentials` Keychain item and contact `https://api.anthropic.com/api/oauth/usage` through `curl`. The PTY path above is the fallback. The application does not write the OAuth credential to its config/cache, but currently passes the bearer header in curl's process arguments, which can expose it to local process inspection. Fix and regression-test this before a broad binary launch; do not treat the earlier PTY-only security description as covering this path.

The Telegram Keychain item's permissive access policy tolerates ad-hoc app re-signing but does not enforce access restricted to a stable signed app identity. Review it alongside Developer ID distribution. Usage results, not just schedules, are cached on disk. No analytics service is included.

Requests use normal Claude Code subscription authentication and consume normal usage. This project cannot increase quota, reset server limits or bypass them. It is independent of and not endorsed by Anthropic.

## Background

The application uses only a process-scoped IOPMAssertion; it does not modify pmset, sudo, or any system-wide power settings. The assertion does not prevent display sleep. In forced-sleep situations such as lid-close, macOS may stop execution; state and network are re-evaluated after wake.

## Telegram

Commands are protected by a numeric user/chat allowlist, a private-chat default, cooldown, escaping, and short-lived per-user confirmation nonces. The polling offset is saved atomically; a bot lock prevents double instances. Raw Telegram updates, full stderr, and the environment are not logged.

## Release

Backend copies are kept in release directories; config/state/logs are separate. Symlink renames are atomic, but the shell installer marks a release healthy and switches `current` before the app build and has no automatic post-health rollback. Manual rollback does not restore the app or retarget every running service. Development app builds can modify the active backend. Five releases are retained with current/previous protected. See [local release limitations](docs/LOCAL_RELEASES.md).

## Incident response

If a secret is exposed, revoke the token first and generate a new one. Logs contain only sanitized JSONL fields. Do not paste secrets into conversations, issues, or the Git history.
