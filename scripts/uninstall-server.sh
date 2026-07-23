#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 2
fi
if [[ ${1:-} != "--yes" && ${1:-} != "--purge" ]]; then
  echo "Use --yes to remove services while preserving shared data, or --purge to remove all data." >&2
  exit 2
fi

SERVICE_USER="claude-starter"
SERVICE_HOME="/var/lib/claude-starter"
APP_BASE="$SERVICE_HOME/.local/share/claude-window-starter"
if id "$SERVICE_USER" >/dev/null 2>&1; then
  uid="$(id -u "$SERVICE_USER")"
  runuser -u "$SERVICE_USER" -- env XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user disable --now \
    claude-window-starter-run.timer claude-window-starter-update-check.timer \
    claude-window-starter-telegram.service >/dev/null 2>&1 || true
  rm -f "$SERVICE_HOME/.config/systemd/user"/claude-window-starter-*.service \
    "$SERVICE_HOME/.config/systemd/user"/claude-window-starter-*.timer
  loginctl disable-linger "$SERVICE_USER" || true
fi
if [[ ${1:-} == "--purge" ]]; then
  userdel --remove "$SERVICE_USER" || true
else
  rm -rf "$APP_BASE/releases" "$APP_BASE/current" "$APP_BASE/previous" "$APP_BASE/repo.git"
  echo "Shared config, credentials, state, and logs were preserved under $APP_BASE/shared."
fi
