# Release preparation

## Current status

The first public release, **v2.2.0**, is published at [GitHub Releases](https://github.com/aetsr/claude-code-window-starter/releases). Installer ZIPs are available for Apple Silicon (arm64) and Intel (x86_64). Each ZIP contains the compiled app, full Python backend, launchd templates, config, and install/uninstall/rollback scripts. The installer validates Python, stages a complete release atomically with journaled rollback, and registers LaunchAgents.

The `.app` built by `build-macos-app.sh dist` alone is ad-hoc signed and depends on an installed backend. It is not a standalone drag-and-drop app. Use the installer ZIP or source installation.

## Automated draft artifacts

`.github/workflows/release.yml` runs on a pushed `v*` tag. It verifies SemVer and matching package/backend/app versions, runs quality checks and tests, builds the wheel and host-native macOS app, packages source and a clearly labeled app preview, generates SHA-256 checksums, and creates a **draft prerelease**. It needs the repository's ordinary `GITHUB_TOKEN` with contents write permission, not signing credentials. It does not publish or promote a release automatically.

Artifacts:

- `claude-code-window-starter-VERSION-macos-arm64-installer.zip`: complete installer for Apple Silicon Macs.
- `claude-code-window-starter-VERSION-macos-x86_64-installer.zip`: complete installer for Intel Macs.
- `claude-code-window-starter-VERSION-source.tar.gz`: tracked source; use source installation instructions.
- `SHA256SUMS` and per-file `.sha256`: verify after download with `shasum -a 256 -c SHA256SUMS`.

The workflow builds on `macos-15` (arm64) and `macos-15-intel` (x86_64) runners. Use [the notes template](RELEASE_NOTES_TEMPLATE.md) before manually publishing a draft.

## Versioning and release steps

Keep Semantic Versioning; do not invent a new v1.0.0. Before tagging, choose the next version based on actual changes and update `pyproject.toml`, `backend/claude_starter/__init__.py`, `macos-app/Resources/Info.plist`, the version in `scripts/build-local.sh`, and the manifest version in `scripts/install-macos.sh`. Increase `CFBundleVersion` for each distributed app build. Move Unreleased notes to the chosen version only when preparing that release. The workflow rejects inconsistent versions.

Run `./scripts/build-local.sh` and CI quality checks on a clean committed revision. Review the resulting draft and checksums, then test a fresh Mac/account before publishing. Tag creation, pushing and publication are maintainer actions; none were performed by this audit.

## Remaining improvements

1. Add Developer ID signing and notarization for a fully trusted public download (currently ad-hoc signed).
2. Review OAuth bearer headers in `curl` argv before a broader launch. See [SECURITY.md](../SECURITY.md).
3. Consider bundling a relocatable Python runtime to remove the external Python requirement.

## Signing/notarization structure to add after packaging

The current draft workflow deliberately builds ad-hoc previews. The future signed pipeline should import a Developer ID certificate into a temporary CI Keychain, sign nested helpers/runtime first with hardened runtime, sign the enclosing app, verify, zip with `ditto`, submit with `xcrun notarytool ... --wait`, staple and validate the app, then recreate the final archive and checksums. Delete the temporary Keychain in an always-run cleanup step. Do not add a misleading enabled notarization step before the complete package exists.

Required secrets for that stage: `MACOS_CERTIFICATE_P12_BASE64`, `MACOS_CERTIFICATE_PASSWORD`, and an App Store Connect notarization API key (`APPLE_API_KEY_P8`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID`). A `DEVELOPER_ID_APPLICATION` signing identity and temporary Keychain password are also needed; the latter can be generated per job. Alternatively use an Apple ID, app-specific password and Team ID with notarytool. Never commit credentials.

Apple requires an appropriate Developer ID identity for this distribution flow; ad-hoc signatures are not notarization. See [Apple Developer ID](https://developer.apple.com/support/developer-id/) and [notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

## ZIP, DMG and Homebrew

Start with a ZIP once the app or installer is complete: it is simple to automate and checksum. A DMG can improve presentation later but cannot solve missing backend installation. A signed installer package may be more appropriate if external runtime and LaunchAgents remain required.

A personal Homebrew tap is a possible later distribution channel. A public Cask needs a complete, versioned upstream download and compliance with [Homebrew Cask requirements](https://docs.brew.sh/Acceptable-Casks), including Gatekeeper checks; acceptance is not guaranteed. Do not publish a cask that merely copies today's incomplete `.app`.
