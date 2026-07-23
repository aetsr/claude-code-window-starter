#!/bin/sh
set -eu
BASE="${CLAUDE_STARTER_HOME:-$HOME/.local/share/claude-window-starter}"
systemctl --user disable --now claude-window-starter-telegram.service 2>/dev/null || true
"$BASE/current/.venv/bin/python" -m claude_starter --home "$BASE" config set telegram.enabled false >/dev/null
echo "Telegram service disabled. Credential retained; remove it manually only if intended."
