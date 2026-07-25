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
python3 -c 'import json,pathlib,platform,sys; pathlib.Path(sys.argv[1]).write_text(json.dumps({"schema_version":2,"application_version":"2.0.0","commit_sha":sys.argv[3],"short_commit_sha":sys.argv[3][:12],"build_time":sys.argv[2],"python_version":platform.python_version(),"healthy":True,"install_result":"local_install"},indent=2)+"\n")' "$RELEASE/release.json" "$STAMP" "$SOURCE_SHA"

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

install -d -m 0755 "$AGENT_DIR"
# Remove the pre-2.0 single-job agent so it cannot trigger a second scheduler.
legacy_label="com.openai.claude-window-starter"
launchctl bootout "$DOMAIN/$legacy_label" >/dev/null 2>&1 || true
rm -f "$AGENT_DIR/$legacy_label.plist"
for plist in "$SOURCE_ROOT"/launchd/*.plist; do
  label="$(basename "$plist" .plist)"
  render_plist "$plist" "$label"
  launchctl bootout "$DOMAIN/$label" >/dev/null 2>&1 || true
  launchctl bootstrap "$DOMAIN" "$AGENT_DIR/$label.plist"
done

python3 -c 'import pathlib,shutil,sys; base=pathlib.Path(sys.argv[1]); releases=sorted((p for p in (base/"releases").iterdir() if p.is_dir()),reverse=True); protected={p.resolve() for p in (base/"current",base/"previous") if p.exists()}; [shutil.rmtree(p) for index,p in enumerate(releases) if index>=5 and p.resolve() not in protected]' "$BASE"
echo "Installed: $APP_DESTINATION"
echo "Backend: $BASE/current"
echo "Automation, Telegram, and background mode remain disabled until explicitly enabled."
