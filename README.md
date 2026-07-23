# Claude Window Starter

Claude Window Starter sends one short, genuine Claude Code subscription request at a configured daily time. Oracle Ubuntu is the primary runtime; a native macOS menu-bar app and local `launchd` agent provide management and backup execution.

The application does **not** use an Anthropic API key, open a web port, scrape Claude, automate MFA/CAPTCHA, or claim that a successful request proves the five-hour usage window started. If the CLI exposes no reliable account-window evidence, status always says that the real request succeeded but the window could not be technically verified.

## Safe defaults

- Automation, Telegram, automatic update, and automatic apply are disabled.
- Prompt: `Respond with OK.`; model: `auto` (verified Haiku attempt, then account default).
- Time: `08:00 Europe/Istanbul`; timeout: 120 seconds; five releases retained.
- Runtime has no third-party Python dependencies.

## Local verification

```sh
PYTHONPATH=backend python3 -m claude_starter --home /tmp/cws --json config init
PYTHONPATH=backend python3 -m claude_starter --home /tmp/cws --json run --dry-run
PYTHONPATH=backend python3 -m unittest discover -s tests -p 'test_*.py'
swift test --package-path macos-app
```

Use `scripts/build-local.sh` for the combined build. `scripts/install-macos.sh` stages the backend under Application Support and installs a disabled-by-default LaunchAgent. Open `macos-app/Package.swift` in Xcode for the menu app.

## Server flow

1. Create an empty private GitHub repository, push this project, protect `main`, and require the CI workflow.
2. Transfer `git archive HEAD` to a temporary Oracle directory over a host-key-verified SSH session; pass the corresponding 40-character commit SHA to `sudo scripts/install-server.sh SHA`. This bootstrap does not require a server Git credential.
3. Run the installed `configure-git-deploy-key.sh` as `claude-starter`, verify GitHub’s published ED25519 fingerprint independently, and add the displayed public key as a read-only deploy key.
4. Set the private repository SSH URL, branch, and `protected_branch_confirmed=true`; `check-update.sh` then creates and fetches the service user’s bare mirror.
5. Generate a subscription token with `claude setup-token`; pipe it to `store-credential.sh claude_oauth_token` without placing it in argv or shell history.
6. Configure non-secret JSON, perform `dry-run.sh`, then explicitly run one real smoke request.

See [Oracle setup](docs/ORACLE.md), [deployment](docs/DEPLOYMENT.md), [Telegram](docs/TELEGRAM.md), [macOS](docs/MACOS.md), and [security](SECURITY.md).

## Stable CLI

```text
status | diagnose | health | run | config | schedule
telegram-bot | telegram-test
update | releases | rollback | logs | service | version
```

All automation consumers use `--json`, which emits a versioned envelope. Real Claude, Telegram, and private Git integration tests remain opt-in through `ENABLE_REAL_CLAUDE_TEST=1`, `ENABLE_REAL_TELEGRAM_TEST=1`, and an explicit deployment-test environment.
