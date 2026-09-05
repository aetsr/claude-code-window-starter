# Homebrew evaluation

Short answer: `brew install --cask claude-window-starter` is **not possible today** and should not be submitted yet. It becomes feasible after the first complete release.

## Why not now

A public Homebrew Cask requires a complete, versioned upstream download that passes Gatekeeper on a clean Mac (see [Cask acceptance rules](https://docs.brew.sh/Acceptable-Casks)). Today's `.app` is ad-hoc signed, contains no Python backend/runtime, and installs nothing (no backend venv, no LaunchAgents) — a cask wrapping it would install a broken app. See [RELEASING.md](RELEASING.md) for the full packaging gap.

## Shortest path to a cask

1. Ship a complete installer (bundled relocatable Python + backend + LaunchAgent bootstrap) as a versioned asset, e.g. `Claude-Window-Starter-2.2.0-macos-arm64.zip` or a `.dmg`/`.pkg`.
2. Sign it with a Developer ID identity and notarize it (`notarytool` + staple); secrets needed: `MACOS_CERTIFICATE_P12_BASE64`, `MACOS_CERTIFICATE_PASSWORD`, notarization API key (`APPLE_API_KEY_P8`, `APPLE_API_KEY_ID`, `APPLE_API_ISSUER_ID`).
3. Publish it as a GitHub Release asset with SHA-256 checksums.
4. Only then write the cask (version, sha256, url, `app` stanza, `zap` stanza) — first in a personal tap for testing, then propose upstream.

Do not publish a cask that copies today's incomplete `.app`.
