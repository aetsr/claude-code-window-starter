# Local releases and rollback

The installer stores backend copies under `~/Library/Application Support/ClaudeWindowStarter/releases`. `current` selects the backend for new UI calls; `previous` is the fallback symlink. These copies are separate from public GitHub Releases.

Source must be clean. Run `scripts/build-local.sh` first for full build/test checks. The installer itself compiles Python, marks the manifest healthy and switches the symlink before building the app. The rename is atomic, but the whole install is not transactional: the shell script does not restore the previous release automatically on failure.

    ./scripts/list-releases.sh
    ./scripts/rollback.sh --yes

Inspect the list before rollback. It changes backend symlinks, not the installed app or all running services. Some launchd jobs use a specific release's Python; changing a symlink does not move those jobs. For a coherent downgrade, back up config/state and install a clean checkout of the desired revision, checking schema compatibility first.

Retention is five releases, with current/previous protected. Config, state, logs and Keychain entries are preserved. The no-argument development `build-macos-app.sh` copies Python files into the active release, so these directories are not immutable under that workflow. Resolve these limitations before advertising atomic, health-gated upgrades. See [release readiness](RELEASING.md).
