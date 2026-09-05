# Install Claude Code 5-Hour Window Starter

This archive includes the compiled macOS app, Python backend and user LaunchAgent installer. You do not need Xcode or Swift to install it.

1. Use the archive matching your Mac: `arm64` for Apple Silicon, `x86_64` for Intel. macOS 13+ is required.
2. Install Python 3.10–3.13 with `venv` and keep it installed for normal operation. An existing compatible Python is sufficient. If needed, use [python.org](https://www.python.org/downloads/macos/). The installer checks compatibility before changing an active installation; it does not download Python or install pip dependencies.
3. Install Claude Code separately and run `claude auth login` for subscription access. No paid Anthropic API key is required.
4. Extract the ZIP and open `Install.command`. Alternatively run `bash scripts/install-macos.sh` from the extracted folder. Read any macOS security prompt carefully. Ad-hoc development candidates are not notarized; a trusted public distribution requires Developer ID signing and notarization. Do not disable Gatekeeper system-wide.
5. The app opens after installation. Review timezone/work hours and usage before enabling automation. Existing installations keep their automation/Telegram preferences.

If `/Applications` is not writable, run:

```bash
CLAUDE_STARTER_APP_PATH="$HOME/Applications/Claude Window Starter.app" bash scripts/install-macos.sh
```

To select Python explicitly:

```bash
CLAUDE_STARTER_PYTHON=/absolute/path/to/python3 bash scripts/install-macos.sh
```

The interpreter must remain available afterward. Installing/upgrading Python can require reinstalling this app's backend environment. Config/state/logs stay under `~/Library/Application Support/ClaudeWindowStarter`. The app and services are staged/checked before activation; handled failures restore the prior app, symlinks and service definitions. Recovery backups remain in `install-backups` and beside the app. Interrupted installations are recovered on the next activation attempt.

For upgrades, install a newer matching archive. For rollback between complete releases, inspect `bash scripts/list-releases.sh`, then use `bash scripts/rollback.sh --yes`. Legacy backend-only releases cannot be fully rolled back by symlink switching; reinstall their matching source instead.

Uninstall with `bash scripts/uninstall-macos.sh`. This keeps local data; `--purge` deliberately removes it. If you used a custom app destination, pass the same `CLAUDE_STARTER_APP_PATH` when uninstalling.

Scheduled requests consume normal Claude subscription usage. The app does not increase quota, bypass limits, or reset the server timer. It is independent of Anthropic.
