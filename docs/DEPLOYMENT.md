# Private Git deployment and rollback

The Mac is the source of truth. The repository owner creates the private remote and pushes with their existing Git authentication. No credential is given to Codex or stored in this project.

Protect `main`, require the `CI` workflow, and add Oracle’s generated public deploy key without write access. The server pins GitHub’s official Ed25519 host key and accepts only the configured GitHub SSH origin.

`check-update.sh` fetches the configured branch into `shared`’s bare mirror and compares exact commit IDs. `deploy-update.sh`:

1. acquires the deployment lock and waits a bounded time for an active Claude run;
2. validates the remote branch head and rejects submodules;
3. checks disk capacity;
4. creates a clean archive with no hooks or untracked files;
5. rejects unsafe archive paths, links, and secret-like content;
6. creates an isolated release and runs compile, unit, config, health, Telegram `getMe` when enabled, and systemd checks;
7. atomically switches `previous` and `current`;
8. verifies post-switch health;
9. restores, restarts, and health-checks the previous release on failure.

`rollback.sh --yes` accepts only a locally installed release marked healthy. Retention keeps at least five releases and never removes `current`, `previous`, a running process release, or the newest additional healthy fallback.

Automatic checks and automatic apply are independent and both default to off. The server reports private GitHub CI as an external protected-branch requirement, not as machine-verified.
