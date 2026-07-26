# Troubleshooting

- **API_KEY_DETECTED**: Remove prohibited API/provider environment variables; do not add credentials outside a subscription session.
- **CLAUDE_NOT_AUTHENTICATED**: Refresh the Claude Code session on your Mac; run a dry-run first, then a real smoke call.
- **NETWORK_UNAVAILABLE** or **pending_connectivity**: The helper will automatically make a single retry when connectivity is restored.
- **ALREADY_RAN_TODAY**: The daily duplicate protection has triggered; a manual run can still be performed.
- **MODEL_UNAVAILABLE**: `auto` tests the Haiku alias before a successful call and falls back to the account default when necessary.
- **LAUNCHD_FAILED**: Reinstall the application; check the `plutil -lint` output of the plist files.
- **NO_HEALTHY_PREVIOUS_RELEASE**: There is no healthy local release to roll back to.
- If the process stops when the lid is closed, this is macOS forced-sleep behavior; pending work is re-evaluated after the device wakes.

Use the Status, Diagnostics, Health check, and Logs buttons in the application for diagnosis. Do not share secrets, full stderr, raw environment, or Telegram update payloads.
