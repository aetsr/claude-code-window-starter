#!/bin/sh
set -eu
BASE="${CLAUDE_STARTER_HOME:-$HOME/Library/Application Support/ClaudeWindowStarter}"
exec "$BASE/current/.venv/bin/python" -m claude_starter --home "$BASE" --json releases
