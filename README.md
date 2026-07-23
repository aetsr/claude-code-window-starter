# Claude Window Starter

Claude Window Starter sends one short, genuine Claude Code subscription request at a configured daily time. The source repository lives on the Mac, the owner pushes it to a private GitHub repository, and Oracle Ubuntu fetches immutable releases through a read-only deploy key.

No Anthropic API key is accepted. The project does not open an inbound port, scrape Claude, automate MFA/CAPTCHA, or claim that a successful request proves the five-hour usage window started.

## Safe defaults

- Automation, Telegram, automatic update checks, and automatic apply are disabled.
- Prompt: `Respond with OK.`; model: `auto`.
- Time: `08:00 Europe/Istanbul`; timeout: 120 seconds.
- Five releases are retained.
- The Python runtime has no third-party dependencies.
- Secrets, local config, state, logs, build output, and machine-specific files are ignored by Git.

## Mac build and installation

```sh
scripts/build-local.sh
scripts/install-macos.sh
open "/Applications/Claude Window Starter.app"
```

The installer creates an ad-hoc signed local app bundle, installs the backend under `~/Library/Application Support/ClaudeWindowStarter`, and loads a disabled-by-default LaunchAgent. Local settings persist in `UserDefaults`; secrets use the macOS Keychain and are never displayed again.

Remove the app while preserving local state:

```sh
scripts/uninstall-macos.sh
```

Use `scripts/uninstall-macos.sh --purge` only when config, state, logs, and Keychain credentials must also be deleted.

## Private Git repository

Codex does not need GitHub credentials and does not push the repository. Use your existing local Git authentication:

```sh
git remote add origin git@github.com:OWNER/PRIVATE_REPO.git
git push -u origin main
git push origin v1.0.0
```

Protect `main`, require the `CI` workflow, and disallow direct bypass where practical. No GitHub API token is stored on Oracle.

## Oracle bootstrap

Create a clean bootstrap archive after the production commit:

```sh
scripts/create-server-bootstrap.sh
```

Transfer the printed archive and checksum with your own SSH client. On Oracle, verify the checksum, extract the archive, run `scripts/diagnose-server.sh`, then run `sudo scripts/install-server.sh COMMIT_SHA`.

The installer:

1. runs a read-only preflight before mutation;
2. verifies the official Claude stable APT signing key;
3. creates the locked `claude-starter` service account;
4. installs an immutable initial release and hardened user services;
5. generates a server-local deploy private key;
6. prints only the public key to add to GitHub.

After the public key is added, configure the private SSH URL and protected branch. Updates use `git fetch` plus `git archive`; the active release is never modified with `git pull`.

See [Oracle setup](docs/ORACLE.md), [deployment and rollback](docs/DEPLOYMENT.md), [Telegram](docs/TELEGRAM.md), [macOS](docs/MACOS.md), and [security](SECURITY.md).

## Stable CLI

```text
status | diagnose | health | run | config | schedule
telegram-bot | telegram-test
update | releases | rollback | logs | service | version
```

Automation consumers use `--json`, which emits the versioned result envelope. Credential input is available through `credential store NAME`, reads stdin only, and never returns the secret.

Real Claude and Telegram tests stay opt-in. Enable them only on the intended target after dry-run and health checks succeed.
