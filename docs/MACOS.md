# macOS application

`scripts/install-macos.sh` creates a local backend release, installs the Claude Window Starter.app bundle into /Applications, and loads launchd agents. The application targets macOS 13+ and supports both Apple Silicon and Intel x86_64 paths.

The menu application calls only the local JSON CLI. Automation now asks only for a same-day busy period (default 08:00–17:00 on weekdays), shows today's anchor preview, the observed reset, source/freshness, and offers an explicit sync button. Fixed-anchor calibration remains under Manual override.

Usage queries check a cache up to 300 seconds old, then the OAuth usage endpoint with the existing Claude Code Keychain credential. The fallback uses a stdlib PTY under `shared/runtime/usage-workspace`, verified app-owned with mode `0700`. Claude runs there with an absolute executable path, allowlisted environment, no tools, `dontAsk` mode, Chrome disabled and an empty MCP configuration. No Terminal Automation permission is involved. See [security limitations](../SECURITY.md).

When the background segment is active, the helper:

- monitors the network path with NWPathMonitor,
- holds a process-scoped IOPMAssertion to prevent idle sleep,
- calls the locked and idempotent Python `schedule --tick` decision,
- allows the display to sleep.

The Swift helper performs no date/window arithmetic. The backend stores plans in UTC and renders them in the configured IANA timezone, including DST transitions. Because lid-close triggers a forced sleep, clamshell operation without accessories is not guaranteed. Missed anchors are not replayed after wake; only the remaining day is considered.

Build with Swift 6.0+ and a compatible macOS SDK:

    scripts/build-macos-app.sh dist
    codesign --verify --deep --strict "dist/Claude Window Starter.app"

The bundle is ad-hoc signed, not notarized. It needs the separately installed Python backend and services; it is not a complete drag-and-drop app. See [release preparation](RELEASING.md). Without `dist`, this script replaces the installed app, syncs the active backend and launches it.
