# Security model

## Credentials

Never paste a token, SSH private key, Git credential, cookie, or raw environment dump into a chat, issue, log, or Git commit.

`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, custom gateways, Bedrock, Vertex, Foundry, and `apiKeyHelper` stop real execution. Oracle accepts only the subscription OAuth token produced by `claude setup-token`.

- Mac secrets are written through SecureField/stdin and stored in Keychain.
- Oracle secrets are entered through hidden stdin and stored with `LoadCredentialEncrypted` when supported, otherwise in mode-0600 files.
- Git push uses the owner’s existing Mac credential.
- Oracle generates its deploy private key locally; only the public key leaves the server.
- Secrets, auth files, SSH private keys, runtime data, and local config are excluded from releases and Git.

## Process isolation

Claude runs with `shell=False`, prompt over stdin, an allowlisted environment, no tools, no session persistence, capability-gated flags, a timeout, and a dedicated runtime directory. Dry-run cannot invoke `claude -p`.

Systemd services run as the password-locked, non-login `claude-starter` user with `NoNewPrivileges`, private temporary/device views, an empty capability set, strict filesystem protection, and no inbound listener.

## Git and release trust

- The Mac is the authoring repository; the user performs remote creation and push.
- Oracle accepts only a configured `git@github.com:OWNER/REPO.git` origin and branch head.
- GitHub’s Ed25519 host key must match `SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`.
- The deploy key has no write permission.
- Updates fetch into a bare mirror and extract a validated `git archive`; hooks, untracked files, submodules, symlinks, path traversal, and secret-like tracked content are rejected.
- Private GitHub CI state is not claimed as machine-verified without a GitHub API credential. Protected `main` and required checks remain an external prerequisite.

## Incident response

Revoke an exposed token/key first, stop affected services, rotate the credential, and review sanitized JSONL logs plus private repository history. Never attach complete stderr, Telegram update payloads, Claude auth files, or shared runtime directories to a report.
