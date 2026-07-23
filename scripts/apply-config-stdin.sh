#!/bin/sh
set -eu
BASE="${CLAUDE_STARTER_HOME:-$HOME/Library/Application Support/ClaudeWindowStarter}"
PYTHON="$BASE/current/.venv/bin/python"
exec "$PYTHON" -m claude_starter --home "$BASE" --json config patch-stdin
