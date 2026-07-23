#!/bin/sh
set -eu
BASE="${CLAUDE_STARTER_HOME:-$HOME/Library/Application Support/ClaudeWindowStarter}"
if [ "${1:-}" != "--yes" ]; then
  echo "Rollback requires --yes after reviewing list-releases.sh." >&2
  exit 2
fi
exec "$BASE/current/.venv/bin/python" -m claude_starter --home "$BASE" --json rollback --yes
