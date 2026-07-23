#!/bin/sh
set -eu
BASE="${CLAUDE_STARTER_HOME:-$HOME/.local/share/claude-window-starter}"
exec "$BASE/current/.venv/bin/python" -m claude_starter --home "$BASE" --json run --manual --trigger server_cli
