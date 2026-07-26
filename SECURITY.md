# Security model

## Secrets

The Telegram token is written to the macOS Keychain via SecureField/stdin. The token is never written to config, state, argv, environment, logs, or a release. The launchd helper reads the token from Keychain and passes it to the bot process via anonymous stdin.

Claude execution runs with `shell=False`, prompt via stdin, an allowlisted environment, an empty tool set, session persistence disabled, capability-gated flags, and a timeout. If prohibited API/provider variables are detected, the real call is aborted.

## Background

The application uses only a process-scoped IOPMAssertion; it does not modify pmset, sudo, or any system-wide power settings. The assertion does not prevent display sleep. In forced-sleep situations such as lid-close, macOS may stop execution; state and network are re-evaluated after wake.

## Telegram

Commands are protected by a numeric user/chat allowlist, a private-chat default, cooldown, escaping, and short-lived per-user confirmation nonces. The polling offset is saved atomically; a bot lock prevents double instances. Raw Telegram updates, full stderr, and the environment are not logged.

## Release

Releases are kept in immutable directories on the Mac. Config, state, logs, and non-Keychain secrets are independent of releases. `current` and `previous` are swapped via a temporary symlink and atomic rename; the previous release is restored on post-health failure. Five releases are retained while active and fallback releases are protected.

## Incident response

If a secret is exposed, revoke the token first and generate a new one. Logs contain only sanitized JSONL fields. Do not paste secrets into conversations, issues, or the Git history.
