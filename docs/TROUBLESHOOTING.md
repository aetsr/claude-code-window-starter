# Troubleshooting

- **API_KEY_DETECTED**: Remove prohibited API/provider environment variables; do not add credentials outside a subscription session.
- **CLAUDE_NOT_AUTHENTICATED**: Run `claude auth login` once interactively on the Mac. The background service never automates subscription login.
- **CLAUDE_USAGE_UNAVAILABLE**: Update Claude Code and confirm that interactive `/usage` is supported. The app rejects welcome, trust, `API Usage Billing`, and incomplete screens as results.
- **TIMEOUT** during `/usage`: Wait for any active Claude run to finish and retry. PTY children are terminated and reaped on every error path.
- **NETWORK_UNAVAILABLE** or **pending_connectivity**: The helper will automatically make a single retry when connectivity is restored.
- **ALREADY_RAN_TODAY**: The daily duplicate protection has triggered; a manual run can still be performed.
- **MODEL_UNAVAILABLE**: `auto` tests the Haiku alias before a successful call and falls back to the account default when necessary.
- **LAUNCHD_FAILED**: Reinstall the application; check the `plutil -lint` output of the plist files.
- **NO_HEALTHY_PREVIOUS_RELEASE**: There is no healthy local release to roll back to.
- If the process stops when the lid is closed, this is macOS forced-sleep behavior; pending work is re-evaluated after the device wakes.

Use the Status, Diagnostics, Health check, and Logs buttons in the application for diagnosis. Do not share secrets, full stderr, raw environment, or Telegram update payloads.

`/usage` does not open Terminal/iTerm and does not require Terminal Automation permission. If a Terminal window appears, verify that the installed release SHA matches the current source; that behavior belongs to an older release.
