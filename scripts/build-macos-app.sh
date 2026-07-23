#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT/dist}"
APP="$OUTPUT/Claude Window Starter.app"
CONTENTS="$APP/Contents"

swift build -c release --package-path "$ROOT/macos-app"
BIN_DIR="$(swift build -c release --package-path "$ROOT/macos-app" --show-bin-path)"

rm -rf "$APP"
install -d -m 0755 "$CONTENTS/MacOS" "$CONTENTS/Resources"
install -m 0755 "$BIN_DIR/ClaudeWindowStarter" "$CONTENTS/MacOS/ClaudeWindowStarter"
install -m 0644 "$ROOT/macos-app/Resources/Info.plist" "$CONTENTS/Info.plist"

plutil -lint "$CONTENTS/Info.plist"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"
echo "$APP"
