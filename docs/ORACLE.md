# Oracle Ubuntu installation

## 1. Prepare on the Mac

Commit the production source, then create the clean archive:

```sh
scripts/create-server-bootstrap.sh
```

The script refuses a dirty repository and prints the archive path and exact commit SHA. Transfer the archive plus `.sha256` file using your own SSH configuration; no private key is copied into the project.

## 2. Verify and diagnose on Oracle

```sh
sha256sum -c claude-window-starter-bootstrap-*.tar.sha256
mkdir claude-window-starter-bootstrap
tar -xf claude-window-starter-bootstrap-*.tar -C claude-window-starter-bootstrap
cd claude-window-starter-bootstrap
scripts/diagnose-server.sh
```

The preflight checks Ubuntu/Debian, ARM64/x86_64, Python 3.10–3.13, systemd, disk/memory, required commands, DNS, HTTPS, Git reachability, and Claude availability without printing secrets.

## 3. Install the initial release

```sh
sudo scripts/install-server.sh FULL_COMMIT_SHA
```

The installer repeats preflight before mutation, verifies Anthropic’s APT key fingerprint, installs Claude Code if necessary, creates the locked non-login `claude-starter` account, enables lingering, installs the initial release, and prints a read-only deploy public key.

Add only that public key to the private repository’s **Deploy keys** without write access.

## 4. Configure the private origin

```sh
BASE=/var/lib/claude-starter/.local/share/claude-window-starter
UID_CWS="$(id -u claude-starter)"
sudo -u claude-starter env XDG_RUNTIME_DIR="/run/user/$UID_CWS" \
  "$BASE/current/.venv/bin/python" -m claude_starter --home "$BASE" \
  config set deployment.repository_url '"git@github.com:OWNER/PRIVATE_REPO.git"'
sudo -u claude-starter env XDG_RUNTIME_DIR="/run/user/$UID_CWS" \
  "$BASE/current/.venv/bin/python" -m claude_starter --home "$BASE" \
  config set deployment.protected_branch_confirmed true
sudo -u claude-starter env XDG_RUNTIME_DIR="/run/user/$UID_CWS" \
  "$BASE/current/scripts/check-update.sh"
```

## 5. Store subscription authentication

Generate a token with `claude setup-token`. On Oracle, run the following command and paste it into the hidden prompt:

```sh
sudo -u claude-starter env \
  CLAUDE_STARTER_HOME=/var/lib/claude-starter/.local/share/claude-window-starter \
  /var/lib/claude-starter/.local/share/claude-window-starter/current/scripts/store-credential.sh \
  claude_oauth_token
```

Run dry-run and health before enabling automation. The timer may be active while application config remains disabled; this cannot send a Claude request.
