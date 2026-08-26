#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$HOME/Library/Application Support/ClaudeWindowStarter"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RELEASE="$BASE/releases/$STAMP"
APP_DESTINATION="${CLAUDE_STARTER_APP_PATH:-/Applications/Claude Window Starter.app}"
AGENT_DIR="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
PATH_VALUE="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SOURCE_SHA="$(git -C "$SOURCE_ROOT" rev-parse --verify HEAD 2>/dev/null || printf 'local')"

if [[ -d "$SOURCE_ROOT/.git" ]] && [[ -n "$(git -C "$SOURCE_ROOT" status --porcelain --untracked-files=normal)" ]]; then
  echo "Refusing to install from a dirty repository. Commit the production source first." >&2
  exit 2
fi

umask 077
install -d -m 0700 "$RELEASE" "$BASE/shared/config" "$BASE/shared/state" "$BASE/shared/logs" "$BASE/shared/runtime"
ditto "$SOURCE_ROOT/backend" "$RELEASE/backend"
python3 -m venv "$RELEASE/.venv"
SITE_PACKAGES="$("$RELEASE/.venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
printf '%s\n' "$RELEASE/backend" > "$SITE_PACKAGES/claude_window_starter.pth"

if [[ ! -f "$BASE/shared/config/config.json" ]]; then
  install -m 0600 "$SOURCE_ROOT/config/config.example.json" "$BASE/shared/config/config.json"
fi

"$RELEASE/.venv/bin/python" -m compileall -q "$RELEASE/backend"
python3 -c 'import json,pathlib,platform,sys; pathlib.Path(sys.argv[1]).write_text(json.dumps({"schema_version":2,"application_version":"2.1.0","commit_sha":sys.argv[3],"short_commit_sha":sys.argv[3][:12],"build_time":sys.argv[2],"python_version":platform.python_version(),"healthy":True,"install_result":"local_install"},indent=2)+"\n")' "$RELEASE/release.json" "$STAMP" "$SOURCE_SHA"

atomic_link() {
  local target="$1"
  local link="$2"
  local temporary="$BASE/.$(basename "$link")-$STAMP"
  ln -s "$target" "$temporary"
  python3 -c 'import os,sys; os.replace(sys.argv[1],sys.argv[2])' "$temporary" "$link"
}

if [[ -L "$BASE/current" ]]; then
  atomic_link "$(readlink "$BASE/current")" "$BASE/previous"
fi
atomic_link "$RELEASE" "$BASE/current"

CLAUDE_STARTER_APP_PATH="$APP_DESTINATION" \
  "$SOURCE_ROOT/scripts/build-macos-app.sh" >/dev/null
codesign --verify --deep --strict "$APP_DESTINATION"

render_plist() {
  local source="$1"
  local label="$2"
  local destination="$AGENT_DIR/$label.plist"
  python3 - "$source" "$destination" "$RELEASE/.venv/bin/python" "$BASE" "$PATH_VALUE" "$APP_DESTINATION/Contents/Helpers/ClaudeWindowStarterAgent" <<'PY'
import pathlib
import sys

source, destination, python, base, path_value, agent = sys.argv[1:]
text = pathlib.Path(source).read_text()
for key, value in {"@@PYTHON@@": python, "@@HOME@@": base, "@@PATH@@": path_value, "@@AGENT@@": agent}.items():
    text = text.replace(key, value)
pathlib.Path(destination).write_text(text)
PY
  chmod 0644 "$destination"
  plutil -lint "$destination" >/dev/null
}

terminate_stale_telegram_worker() {
  local mode="${1:-all}"
  local lock_file="$BASE/shared/runtime/telegram.lock"
  local worker_pid=""
  local worker_command=""
  if [[ ! -f "$lock_file" ]]; then
    return
  fi
  read -r worker_pid < "$lock_file" || true
  if [[ ! "$worker_pid" =~ ^[1-9][0-9]*$ ]] || ! kill -0 "$worker_pid" 2>/dev/null; then
    return
  fi
  worker_command="$(/bin/ps -p "$worker_pid" -o command= 2>/dev/null || true)"
  if [[ "$worker_command" != *" -m claude_starter "* ||
        "$worker_command" != *" --home $BASE "* ||
        "$worker_command" != *" telegram-bot "* ]]; then
    echo "Ignoring stale Telegram lock PID $worker_pid: process identity did not match." >&2
    return
  fi
  if [[ "$mode" == "legacy" && "$worker_command" == *" --supervisor-pid "* ]]; then
    return
  fi
  kill -TERM "$worker_pid"
  for _ in {1..12}; do
    if ! kill -0 "$worker_pid" 2>/dev/null; then
      return
    fi
    sleep 1
  done
  echo "Telegram worker PID $worker_pid did not stop after supervisor handoff." >&2
  exit 1
}

terminate_all_telegram_supervisors() {
  # Kill every ClaudeWindowStarterAgent running in telegram mode so only the
  # freshly bootstrapped launchd job survives.  The supervisor lock file
  # guarantees at most one instance, but stale processes from a previous
  # install may still be alive.
  local pids
  pids="$(pgrep -f 'ClaudeWindowStarterAgent telegram' 2>/dev/null || true)"
  for pid in $pids; do
    kill -TERM "$pid" 2>/dev/null || true
  done
  if [[ -n "$pids" ]]; then
    for _ in {1..10}; do
      pids="$(pgrep -f 'ClaudeWindowStarterAgent telegram' 2>/dev/null || true)"
      [[ -z "$pids" ]] && break
      sleep 0.5
    done
    for pid in $pids; do
      kill -KILL "$pid" 2>/dev/null || true
    done
  fi
  rm -f "$BASE/shared/runtime/telegram_supervisor.lock"
  rm -f "$BASE/shared/runtime/telegram_supervisor.json"
}

install -d -m 0755 "$AGENT_DIR"
# Remove the pre-2.0 single-job agent so it cannot trigger a second scheduler.
legacy_label="com.claude-window-starter"
launchctl bootout "$DOMAIN/$legacy_label" >/dev/null 2>&1 || true
rm -f "$AGENT_DIR/$legacy_label.plist"

# Bootout all managed jobs and kill all telegram supervisors/workers before
# bootstrapping fresh instances.
for plist in "$SOURCE_ROOT"/launchd/*.plist; do
  label="$(basename "$plist" .plist)"
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
done
terminate_all_telegram_supervisors
terminate_stale_telegram_worker

for plist in "$SOURCE_ROOT"/launchd/*.plist; do
  label="$(basename "$plist" .plist)"
  render_plist "$plist" "$label"
  launchctl bootstrap "$DOMAIN" "$AGENT_DIR/$label.plist"
done
# A KeepAlive restart can briefly race with the first bootstrap and start one
# pre-upgrade worker. Remove only that verified legacy argv; a current worker
# carrying --supervisor-pid is never touched.
sleep 2
terminate_stale_telegram_worker legacy

python3 -c 'import pathlib,shutil,sys; base=pathlib.Path(sys.argv[1]); releases=sorted((p for p in (base/"releases").iterdir() if p.is_dir()),reverse=True); protected={p.resolve() for p in (base/"current",base/"previous") if p.exists()}; [shutil.rmtree(p) for index,p in enumerate(releases) if index>=5 and p.resolve() not in protected]' "$BASE"
echo "Installed: $APP_DESTINATION"
echo "Backend: $BASE/current"
echo "Existing automation, Telegram, and background preferences were preserved."
