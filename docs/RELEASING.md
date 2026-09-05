# Release preparation

## Current status

Audit on 2026-09-05: GitHub returned no Releases. A local `v1.0.0` tag exists; a tag or dated changelog section does not establish a published binary release. Python, package metadata, installer and app report **2.1.0**. Previously the README/changelog implied **2.2.0** had shipped; its changes now sit under Unreleased until a deliberate version bump and tag.

The `.app` built by `build-macos-app.sh dist` is ad-hoc signed, contains Swift executables, and depends on `Application Support/ClaudeWindowStarter/current/.venv/bin/python`. It does not bundle Python/backend or bootstrap its LaunchAgents. Publishing it as a drag-and-drop app would fail on a clean Mac.

## Automated draft artifacts

`.github/workflows/release.yml` runs on a pushed `v*` tag. It verifies SemVer and matching package/backend/app versions, runs quality checks and tests, builds the wheel and host-native macOS app, packages source and a clearly labeled app preview, generates SHA-256 checksums, and creates a **draft prerelease**. It needs the repository's ordinary `GITHUB_TOKEN` with contents write permission, not signing credentials. It does not publish or promote a release automatically.

Artifacts:

- `claude-code-window-starter-VERSION-source.tar.gz`: tracked source; use source installation instructions.
- `claude-code-window-starter-VERSION-macos-ARCH-app-preview.zip`: Swift-only development preview, not a complete installer.
- Python wheel: backend only, not the full macOS app.
- `SHA256SUMS`: verify after download with `shasum -a 256 -c SHA256SUMS` from the directory containing all assets.

The initial workflow builds the `macos-15` runner's native architecture and labels it from `uname -m`. It does not claim a universal binary. Separate Intel verification is required before advertising Intel downloads. Use [the notes template](RELEASE_NOTES_TEMPLATE.md) before manually publishing a draft. A draft is not a downloadable public release.

## Versioning and release steps

Keep Semantic Versioning; do not invent a new v1.0.0. Before tagging, choose the next version based on actual changes and update `pyproject.toml`, `backend/claude_starter/__init__.py`, `macos-app/Resources/Info.plist`, the version in `scripts/build-local.sh`, and the manifest version in `scripts/install-macos.sh`. Increase `CFBundleVersion` for each distributed app build. Move Unreleased notes to the chosen version only when preparing that release. The workflow rejects inconsistent versions.

Run `./scripts/build-local.sh` and CI quality checks on a clean committed revision. Review the resulting draft and checksums, then test a fresh Mac/account before publishing. Tag creation, pushing and publication are maintainer actions; none were performed by this audit.

## What blocks a complete downloadable app

1. Package the Python backend and a relocatable Python runtime, or provide a complete installer that validates an external Python and creates the backend/LaunchAgents. Copying a development virtualenv is not portable. Bundling Python is feasible, but requires architecture-specific runtime updates, license notices and signing all nested executable code.
2. Fix shell installation staging and rollback: it currently marks the manifest healthy and switches `current` before the Swift build, and has no post-health rollback. Backend symlink rollback does not restore the app or restart all services onto the selected backend. Test failure recovery before claiming atomic upgrades.
3. Review OAuth bearer headers in `curl` argv, broad Telegram Keychain ACLs, and changes to the usage endpoint before a broad launch. See [SECURITY.md](../SECURITY.md). No credential behavior was changed by the audit.
4. Validate clean install, upgrade, uninstall, auth, cache behavior and sleep/wake on the claimed architectures/macOS versions. The mixed English/Turkish interface also needs a localization decision.
5. Add Developer ID signing/notarization for a normal trusted public download, plus actual screenshots and release notes.

## Signing/notarization structure to add after packaging

The current draft workflow deliberately builds ad-hoc previews. The future signed pipeline should import a Developer ID certificate into a temporary CI Keychain, sign nested helpers/runtime first with hardened runtime, sign the enclosing app, verify, zip with `ditto`, submit with `xcrun notarytool ... --wait`, staple and validate the app, then recreate the final archive and checksums. Delete the temporary Keychain in an always-run cleanup step. Do not add a misleading enabled notarization step before the complete package exists.

Required secrets for that stage: `MACOS_CERTIFICATE_P12_BASE64`, `MACOS_CERTIFICATE_PASSWORD`, and an App Store Connect notarization API key (`APPLE_API_KEY_P8`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID`). A `DEVELOPER_ID_APPLICATION` signing identity and temporary Keychain password are also needed; the latter can be generated per job. Alternatively use an Apple ID, app-specific password and Team ID with notarytool. Never commit credentials.

Apple requires an appropriate Developer ID identity for this distribution flow; ad-hoc signatures are not notarization. See [Apple Developer ID](https://developer.apple.com/support/developer-id/) and [notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

## ZIP, DMG and Homebrew

Start with a ZIP once the app or installer is complete: it is simple to automate and checksum. A DMG can improve presentation later but cannot solve missing backend installation. A signed installer package may be more appropriate if external runtime and LaunchAgents remain required.

A personal Homebrew tap is a possible later distribution channel. A public Cask needs a complete, versioned upstream download and compliance with [Homebrew Cask requirements](https://docs.brew.sh/Acceptable-Casks), including Gatekeeper checks; acceptance is not guaranteed. Do not publish a cask that merely copies today's incomplete `.app`.
