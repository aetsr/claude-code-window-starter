# macOS application and local backend

Run `scripts/install-macos.sh` from the repository. It creates a release backend under Application Support, builds an ad-hoc signed `Claude Window Starter.app`, installs it in `/Applications`, and loads the LaunchAgent. Automation stays disabled.

The menu app targets macOS 13+ and has no third-party framework. Connection/configuration settings persist in `UserDefaults`; OAuth and Telegram values go to Keychain. Stored secret values are never loaded back into visible fields.

Oracle Server is the default target. Remote commands use `/usr/bin/ssh` with separate arguments, batch mode, a specific identity path, strict host checking, and an app-owned `known_hosts` file. Scan the Oracle Ed25519 key, independently compare its SHA256 fingerprint in Oracle Console, and only then press **Trust verified key**. A later key change stops SSH.

This Mac mode calls the same installed JSON backend locally. The LaunchAgent PATH includes the standard native Claude locations, but its config remains disabled until explicitly enabled. Do not enable both Oracle and Mac daily schedules unless two automatic requests are intended.

Build without installing:

```sh
scripts/build-macos-app.sh
codesign --verify --deep --strict "dist/Claude Window Starter.app"
```

The local bundle is intentionally ad-hoc signed for this Mac. App Store distribution and notarization are outside this private deployment.
