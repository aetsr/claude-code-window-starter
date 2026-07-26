# Local releases and rollback

The installer stores every backend copy as an immutable release under `~/Library/Application Support/ClaudeWindowStarter/releases`. `current` is the running symlink; `previous` is the last fallback symlink.

For a new release, the source must be clean and Python syntax/import/test checks along with the application build must pass. The symlink transition is atomic. If the health check fails, the previous release is restored.

    claude-window-starter --json releases
    claude-window-starter --json rollback --yes

Retention is five releases; the `current` and `previous` releases are never deleted. Config, state, logs, and Keychain entries are preserved across release changes.
