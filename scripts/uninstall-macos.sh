#!/usr/bin/env bash
set -euo pipefail

BASE="$HOME/Library/Application Support/ClaudeWindowStarter"
AGENT_DIR="$HOME/Library/LaunchAgents"
APP="${CLAUDE_STARTER_APP_PATH:-/Applications/Claude Window Starter.app}"
DOMAIN="gui/$(id -u)"
PURGE=false

if [[ "${1:-}" == "--purge" ]]; then
  PURGE=true
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--purge]" >&2
  exit 2
fi

for plist in "$AGENT_DIR"/com.claude-window-starter.*.plist; do
  [[ -e "$plist" ]] || continue
  label="$(basename "$plist" .plist)"
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  rm -f "$plist"
done
rm -rf "$APP"

if [[ "$PURGE" == true ]]; then
  rm -rf "$BASE"
  defaults delete com.claude-window-starter >/dev/null 2>&1 || true
  echo "Application, backend, settings, and local files removed. Keychain entries remain per account."
else
  echo "Application and launch agents removed. Shared config/state remain at: $BASE"
fi
