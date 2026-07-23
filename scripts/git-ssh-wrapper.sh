#!/bin/sh
set -eu
BASE="${CLAUDE_STARTER_HOME:-$HOME/.local/share/claude-window-starter}"
exec /usr/bin/ssh -F "$BASE/shared/config/git_ssh_config" "$@"
