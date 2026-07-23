# macOS menu app and launchd

Open `macos-app/Package.swift` in Xcode or run `swift build --package-path macos-app`. The app targets macOS 13+, uses `MenuBarExtra`, Security.framework Keychain storage, and Foundation `Process`; it has no third-party framework.

Oracle Server is the default mode. The app executes the stable backend JSON CLI over `/usr/bin/ssh` with separate arguments and strict known_hosts checking. Scan the server ED25519 key, compare its SHA256 fingerprint through an independent Oracle console session, then explicitly trust it. A changed host key blocks every operation.

This Mac mode uses the same Python backend installed by `scripts/install-macos.sh`. The LaunchAgent is disabled logically because config starts with `enabled=false`. Do not enable both Oracle and Mac timers unless two automatic daily requests are intended.

Secure fields may temporarily store OAuth/Telegram values in the macOS Keychain and transfer them over verified SSH stdin. The app never displays stored values or reads SSH private-key contents.
