# macOS application

`scripts/install-macos.sh` creates a local backend release, installs the Claude Window Starter.app bundle into /Applications, and loads launchd agents. The application targets macOS 13+ and supports both Apple Silicon and Intel x86_64 paths.

The menu application calls only the local JSON CLI. The Claude, Telegram, Maintenance, and Logs tabs all use the same backend contract.

When the background segment is active, the helper:

- monitors the network path with NWPathMonitor,
- holds a process-scoped IOPMAssertion to prevent idle sleep,
- reports the scheduled time and pending network state to the Python backend,
- allows the display to sleep.

Because lid-close triggers a forced sleep, clamshell operation without accessories is not guaranteed. If the system sleeps, `pending_automatic` is written to disk and a single retry is performed when connectivity is restored after wake.

Build:

    scripts/build-macos-app.sh
    codesign --verify --deep --strict "dist/Claude Window Starter.app"

The bundle is ad-hoc signed; App Store signing and notarization are out of scope.
