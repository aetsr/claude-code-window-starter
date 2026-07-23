# Private GitHub deployment and rollback

Protect `main`, disallow direct pushes/bypass where possible, and require the `CI` workflow. Add the server-generated public key under repository **Deploy keys** without write access. Compare the observed `github.com` fingerprint with GitHub’s official SSH-key fingerprint before allowing `configure-git-deploy-key.sh` to write known_hosts.

Set these non-secret values through the CLI, Telegram, or SwiftUI:

```json
{
  "deployment": {
    "repository_url": "git@github.com:OWNER/PRIVATE_REPO.git",
    "branch": "main",
    "protected_branch_confirmed": true
  }
}
```

`check-update.sh` fetches the configured branch and compares exact commit IDs. `deploy-update.sh` holds an update lock, waits for the Claude lock, builds a separate release from `git archive`, runs tests and health checks, atomically changes symlinks, restarts the bot briefly, and rolls back on failed post-health.

`list-releases.sh` shows local manifests. `rollback.sh --yes` accepts only the previous locally installed release marked healthy; Telegram never accepts an arbitrary commit. Current, previous, and healthy fallback releases are protected from retention cleanup.

Automatic updates are off. Enabling the check timer produces notification-only behavior unless `auto_apply_updates` is also explicitly enabled. The server cannot attest private GitHub Actions status without an API credential, so it never labels CI as machine-verified.
