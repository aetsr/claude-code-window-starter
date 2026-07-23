# Security model

## Credentials

`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, custom gateways, cloud providers, and `apiKeyHelper` stop real execution. Oracle accepts only the subscription OAuth token produced by `claude setup-token`. Secrets are loaded from systemd credentials; a 0600 file is the compatibility fallback. Telegram/OAuth tokens, Claude auth, SSH private keys, deploy keys, cookies, and authorization headers are never logged or returned by status.

The OAuth setup token is long-lived but finite; record its creation date outside the repository and renew it before its one-year validity ends. Never commit `shared/`, `.env`, credentials, private keys, or Claude’s auth directory.

## Process isolation

Claude runs with `shell=False`, stdin prompt input, an allowlisted environment, no tools, no session persistence, no browser integration, timeout, and a dedicated runtime directory. Capability flags are derived from the target’s real `claude --help`. Dry-run cannot invoke `claude -p`.

Systemd user services run as the locked `claude-starter` account with `NoNewPrivileges`, filesystem restrictions, and no inbound listener. Telegram uses outbound HTTPS long polling only.

## Trust boundaries

- SSH and Git require pinned host keys; key changes stop the operation.
- The deploy key is separate, read-only, and mode 0600.
- Production targets exactly the configured `origin/main` commit.
- Private GitHub CI status cannot be independently queried with only an SSH deploy key. Required checks and protected `main` are an external prerequisite and are reported as such.
- Repository archives reject path traversal, links, and secret-like tracked paths before extraction.

Report suspected credential exposure by revoking the affected token/key first, stopping services, rotating credentials, and reviewing sanitized event logs plus the private repository history.
