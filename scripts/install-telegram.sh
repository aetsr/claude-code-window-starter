#!/usr/bin/env bash
set -euo pipefail

allowed_user="${1:-}"
allowed_chat="${2:-}"
if [[ ! "$allowed_user" =~ ^-?[0-9]+$ ]]; then
  echo "Usage: install-telegram.sh ALLOWED_USER_ID [ALLOWED_CHAT_ID]" >&2
  exit 2
fi
if [[ -n "$allowed_chat" && ! "$allowed_chat" =~ ^-?[0-9]+$ ]]; then
  echo "Chat ID must be numeric" >&2
  exit 2
fi

BASE="${CLAUDE_STARTER_HOME:-$HOME/.local/share/claude-window-starter}"
PYTHON="$BASE/current/.venv/bin/python"
echo "Paste the BotFather token; input will not be echoed:" >&2
IFS= read -rs token
printf '\n' >&2
printf '%s\n' "$token" | "$BASE/current/scripts/store-credential.sh" telegram_token
unset token
"$PYTHON" -m claude_starter --home "$BASE" config set telegram.allowed_user_ids "[$allowed_user]" >/dev/null
if [[ -n "$allowed_chat" ]]; then
  "$PYTHON" -m claude_starter --home "$BASE" config set telegram.allowed_chat_ids "[$allowed_chat]" >/dev/null
  "$PYTHON" -m claude_starter --home "$BASE" config set telegram.notification_chat_id "$allowed_chat" >/dev/null
fi
"$PYTHON" -m claude_starter --home "$BASE" config set telegram.enabled true >/dev/null
"$PYTHON" -m claude_starter --home "$BASE" --json telegram-test
systemctl --user enable --now claude-window-starter-telegram.service
