# macOS application

`scripts/install-macos.sh` creates a local backend release, installs the Claude Window Starter.app bundle into /Applications, and loads launchd agents. The application targets macOS 13+ and supports both Apple Silicon and Intel x86_64 paths.

The menu application calls only the local JSON CLI. Automation now asks only for a same-day busy period (default 08:00–17:00 on weekdays), shows today's anchor preview, the observed reset, source/freshness, and offers an explicit sync button. Fixed-anchor calibration remains under Manual override.

The Telegram `/usage` command uses a stdlib pseudo-terminal under `shared/runtime/usage-workspace`. The directory is verified as app-owned with mode `0700`; Claude is launched there with an absolute executable path, an allowlisted environment, no tools, `dontAsk` permission mode, Chrome disabled, and a strict empty MCP configuration. No GUI application or macOS Terminal Automation permission is involved.

When the background segment is active, the helper:

- monitors the network path with NWPathMonitor,
- holds a process-scoped IOPMAssertion to prevent idle sleep,
- calls the locked and idempotent Python `schedule --tick` decision,
- allows the display to sleep.

The Swift helper performs no date/window arithmetic. The backend stores plans in UTC and renders them in the configured IANA timezone, including DST transitions. Because lid-close triggers a forced sleep, clamshell operation without accessories is not guaranteed. Missed anchors are not replayed after wake; only the remaining day is considered.

Build:

    scripts/build-macos-app.sh
    codesign --verify --deep --strict "dist/Claude Window Starter.app"

The bundle is ad-hoc signed; App Store signing and notarization are out of scope.
