#!/usr/bin/env bash
# Build an artifact only. Installation and activation are separate transactions.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT/dist}"
APP_DEST="$OUTPUT/Claude Window Starter.app"
SIGN_IDENTITY="${CLAUDE_STARTER_SIGN_IDENTITY:--}"
mkdir -p "$OUTPUT"
swift build -c release --package-path "$ROOT/macos-app"
BIN_DIR="$(swift build -c release --package-path "$ROOT/macos-app" --show-bin-path)"
STAGING="$(mktemp -d "$OUTPUT/.app-build.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT
APP="$STAGING/Claude Window Starter.app"
CONTENTS="$APP/Contents"
install -d -m 0755 "$CONTENTS/MacOS" "$CONTENTS/Helpers" "$CONTENTS/Resources"
install -m 0755 "$BIN_DIR/ClaudeWindowStarter" "$CONTENTS/MacOS/ClaudeWindowStarter"
install -m 0755 "$BIN_DIR/ClaudeWindowStarterAgent" "$CONTENTS/Helpers/ClaudeWindowStarterAgent"
install -m 0644 "$ROOT/macos-app/Resources/Info.plist" "$CONTENTS/Info.plist"
install -m 0644 "$ROOT/macos-app/Resources/AppIcon.icns" "$CONTENTS/Resources/AppIcon.icns"
plutil -lint "$CONTENTS/Info.plist" >/dev/null
SIGN_OPTIONS=(--force --sign "$SIGN_IDENTITY")
if [[ "$SIGN_IDENTITY" != - ]]; then SIGN_OPTIONS+=(--options runtime --timestamp); fi
codesign "${SIGN_OPTIONS[@]}" "$CONTENTS/Helpers/ClaudeWindowStarterAgent"
codesign "${SIGN_OPTIONS[@]}" "$APP"
codesign --verify --deep --strict "$APP"
# Preserve the prior artifact until compilation and signing both succeed.
if [[ -e "$APP_DEST" ]]; then mv "$APP_DEST" "$STAGING/previous.app"; fi
mv "$APP" "$APP_DEST"
echo "Built: $APP_DEST"
