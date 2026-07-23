#!/usr/bin/env bash
set -euo pipefail

BASE="$HOME/Library/Application Support/ClaudeWindowStarter"
AGENT="$HOME/Library/LaunchAgents/com.openai.claude-window-starter.plist"
APP="${CLAUDE_STARTER_APP_PATH:-/Applications/Claude Window Starter.app}"
DOMAIN="gui/$(id -u)"
PURGE=false

if [[ "${1:-}" == "--purge" ]]; then
  PURGE=true
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--purge]" >&2
  exit 2
fi

launchctl bootout "$DOMAIN/com.openai.claude-window-starter" >/dev/null 2>&1 || true
rm -f "$AGENT"
rm -rf "$APP"

if [[ "$PURGE" == true ]]; then
  rm -rf "$BASE"
  defaults delete com.openai.claude-window-starter >/dev/null 2>&1 || true
  security delete-generic-password -s com.openai.claude-window-starter >/dev/null 2>&1 || true
  echo "Application, backend, settings, and local credentials removed."
else
  echo "Application and LaunchAgent removed. Shared config/state remain at: $BASE"
fi
