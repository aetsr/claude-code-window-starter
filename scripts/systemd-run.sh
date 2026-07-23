#!/bin/sh
set -eu

BASE="${CLAUDE_STARTER_HOME:-$HOME/.local/share/claude-window-starter}"
PYTHON="$BASE/current/.venv/bin/python"

case "${1:-}" in
  automatic)
    exec "$PYTHON" -m claude_starter --json run --automatic --trigger automatic
    ;;
  telegram)
    exec "$PYTHON" -m claude_starter --json run --manual --trigger telegram
    ;;
  macos_ui)
    exec "$PYTHON" -m claude_starter --json run --manual --trigger macos_ui
    ;;
  dry-run)
    exec "$PYTHON" -m claude_starter --json run --dry-run --trigger telegram
    ;;
  *)
    printf '%s\n' "Invalid trigger" >&2
    exit 2
    ;;
esac
