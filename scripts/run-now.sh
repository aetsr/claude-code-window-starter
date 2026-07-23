#!/bin/sh
set -eu
BASE="${CLAUDE_STARTER_HOME:-$HOME/Library/Application Support/ClaudeWindowStarter}"
AGENT="${CLAUDE_STARTER_APP_PATH:-/Applications/Claude Window Starter.app}/Contents/Helpers/ClaudeWindowStarterAgent"
if [ -x "$AGENT" ]; then
  exec "$AGENT" run -m claude_starter --home "$BASE" --json run --manual --trigger macos_ui
fi
exec "$BASE/current/.venv/bin/python" -m claude_starter --home "$BASE" --json run --manual --trigger macos_ui
