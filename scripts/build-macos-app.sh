#!/usr/bin/env bash
# Build the Swift app AND sync the Python backend to the active release,
# then install directly to /Applications. No intermediate dist/ step.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DEST="${CLAUDE_STARTER_APP_PATH:-/Applications/Claude Window Starter.app}"
CONTENTS="$APP_DEST/Contents"
BASE="$HOME/Library/Application Support/ClaudeWindowStarter"

# ── 1. Build Swift binaries ──────────────────────────────────────────────────
echo "Building Swift app..."
swift build -c release --package-path "$ROOT/macos-app"
BIN_DIR="$(swift build -c release --package-path "$ROOT/macos-app" --show-bin-path)"

# ── 2. Install .app to /Applications ─────────────────────────────────────────
echo "Installing to $APP_DEST ..."
pkill -x "Claude Window Starter" 2>/dev/null || true
sleep 0.5

rm -rf "$APP_DEST"
install -d -m 0755 "$CONTENTS/MacOS" "$CONTENTS/Helpers" "$CONTENTS/Resources"
install -m 0755 "$BIN_DIR/ClaudeWindowStarter"      "$CONTENTS/MacOS/ClaudeWindowStarter"
install -m 0755 "$BIN_DIR/ClaudeWindowStarterAgent" "$CONTENTS/Helpers/ClaudeWindowStarterAgent"
install -m 0644 "$ROOT/macos-app/Resources/Info.plist" "$CONTENTS/Info.plist"
if [[ -f "$ROOT/macos-app/Resources/AppIcon.icns" ]]; then
  install -m 0644 "$ROOT/macos-app/Resources/AppIcon.icns" "$CONTENTS/Resources/AppIcon.icns"
fi
plutil -lint "$CONTENTS/Info.plist" >/dev/null
codesign --force --deep --sign - "$APP_DEST"
codesign --verify --deep --strict "$APP_DEST"

# ── 3. Sync Python backend to active release (dev workflow) ──────────────────
if [[ -L "$BASE/current" ]]; then
  RELEASE="$(readlink "$BASE/current")"
  DEST_PY="$RELEASE/backend/claude_starter"
  if [[ -d "$DEST_PY" ]]; then
    echo "Syncing Python backend → $DEST_PY ..."
    cp "$ROOT/backend/claude_starter/"*.py "$DEST_PY/"
  fi
fi

# ── 4. Launch ─────────────────────────────────────────────────────────────────
open "$APP_DEST"
echo "Done: $APP_DEST"
