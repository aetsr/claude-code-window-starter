#!/bin/sh
set -eu
BASE="${CLAUDE_STARTER_HOME:-$HOME/.local/share/claude-window-starter}"
PYTHON="$BASE/current/.venv/bin/python"
"$PYTHON" -m claude_starter --home "$BASE" --json config patch-stdin
"$PYTHON" -m claude_starter --home "$BASE" --json schedule --apply-systemd >/dev/null
systemctl --user daemon-reload
systemctl --user restart claude-window-starter-run.timer
