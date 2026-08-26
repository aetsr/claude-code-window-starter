#!/usr/bin/env bash
# Build the Swift app. With an output-directory argument, create a standalone
# bundle there for CI/verification. Without one, install the development build
# and sync the active local backend.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT_MODE=false
if [[ $# -gt 0 ]]; then
  ARTIFACT_MODE=true
  APP_DEST="$1/Claude Window Starter.app"
else
  APP_DEST="${CLAUDE_STARTER_APP_PATH:-/Applications/Claude Window Starter.app}"
fi
CONTENTS="$APP_DEST/Contents"
BASE="$HOME/Library/Application Support/ClaudeWindowStarter"

# ── 1. Build Swift binaries ──────────────────────────────────────────────────
echo "Building Swift app..."
swift build -c release --package-path "$ROOT/macos-app"
BIN_DIR="$(swift build -c release --package-path "$ROOT/macos-app" --show-bin-path)"

# ── 2. Install .app to /Applications ─────────────────────────────────────────
echo "Installing to $APP_DEST ..."
APP_EXECUTABLE="$APP_DEST/Contents/MacOS/ClaudeWindowStarter"
while read -r app_pid app_command; do
  if [[ "$app_command" == "$APP_EXECUTABLE" || "$app_command" == "$APP_EXECUTABLE "* ]]; then
    kill -TERM "$app_pid" 2>/dev/null || true
  fi
done < <(/bin/ps -axo pid=,command=)
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
if [[ "$ARTIFACT_MODE" == false && -L "$BASE/current" ]]; then
  RELEASE="$(readlink "$BASE/current")"
  DEST_PY="$RELEASE/backend/claude_starter"
  if [[ -d "$DEST_PY" ]]; then
    echo "Syncing Python backend → $DEST_PY ..."
    cp "$ROOT/backend/claude_starter/"*.py "$DEST_PY/"
  fi
fi

# ── 4. Launch ─────────────────────────────────────────────────────────────────
if [[ "$ARTIFACT_MODE" == false ]]; then
  open "$APP_DEST"
fi
echo "Done: $APP_DEST"
