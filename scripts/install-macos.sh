#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$HOME/Library/Application Support/ClaudeWindowStarter"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$$"
RELEASE="$BASE/releases/$STAMP"
APP_DESTINATION="${CLAUDE_STARTER_APP_PATH:-/Applications/Claude Window Starter.app}"
AGENT="$HOME/Library/LaunchAgents/com.openai.claude-window-starter.plist"
DOMAIN="gui/$(id -u)"
LABEL="com.openai.claude-window-starter"
PATH_VALUE="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
SOURCE_SHA="$(git -C "$SOURCE_ROOT" rev-parse --verify HEAD)"

if [[ -n "$(git -C "$SOURCE_ROOT" status --porcelain --untracked-files=normal)" ]]; then
  echo "Refusing to install from a dirty repository. Commit the production source first." >&2
  exit 2
fi

umask 077
install -d -m 0700 \
  "$RELEASE" \
  "$BASE/shared/config" \
  "$BASE/shared/state" \
  "$BASE/shared/logs" \
  "$BASE/shared/runtime" \
  "$BASE/shared/secrets"

ditto "$SOURCE_ROOT/backend" "$RELEASE/backend"
python3 -m venv "$RELEASE/.venv"
SITE_PACKAGES="$("$RELEASE/.venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
printf '%s\n' "$RELEASE/backend" > "$SITE_PACKAGES/claude_window_starter.pth"
install -d -m 0755 "$RELEASE/scripts"
install -m 0755 "$SOURCE_ROOT/scripts/apply-config-stdin.sh" "$RELEASE/scripts/"

if [[ ! -f "$BASE/shared/config/config.json" ]]; then
  install -m 0600 "$SOURCE_ROOT/config/config.example.json" "$BASE/shared/config/config.json"
  "$RELEASE/.venv/bin/python" -m claude_starter \
    --home "$BASE" --json config set execution_mode '"this_mac"' >/dev/null
fi

"$RELEASE/.venv/bin/python" -m claude_starter \
  --home "$BASE" --json health --no-services >/dev/null

python3 -c \
  'import json,pathlib,platform,sys; pathlib.Path(sys.argv[1]).write_text(json.dumps({"schema_version":1,"application_version":"1.0.0","commit_sha":sys.argv[3],"short_commit_sha":sys.argv[3][:12],"branch":"main","build_time":sys.argv[2],"python_version":platform.python_version(),"healthy":True,"deploy_result":"local_install"},indent=2)+"\n")' \
  "$RELEASE/release.json" "$STAMP" "$SOURCE_SHA"

atomic_link() {
  local target="$1"
  local link="$2"
  local temporary="$BASE/.$(basename "$link")-$STAMP"
  ln -s "$target" "$temporary"
  python3 -c 'import os,sys; os.replace(sys.argv[1],sys.argv[2])' "$temporary" "$link"
}

if [[ -L "$BASE/current" ]] && current_target="$(readlink "$BASE/current")"; then
  atomic_link "$current_target" "$BASE/previous"
fi
atomic_link "$RELEASE" "$BASE/current"

install -d -m 0755 "$(dirname "$AGENT")"
python3 -c \
  'import pathlib,sys; text=pathlib.Path(sys.argv[1]).read_text(); replacements={"@@PYTHON@@":sys.argv[3],"@@HOME@@":sys.argv[4],"@@PATH@@":sys.argv[5]}; [None for key,value in replacements.items() if not (text:=text.replace(key,value))]; pathlib.Path(sys.argv[2]).write_text(text)' \
  "$SOURCE_ROOT/launchd/com.openai.claude-window-starter.plist" \
  "$AGENT" \
  "$RELEASE/.venv/bin/python" \
  "$BASE" \
  "$PATH_VALUE"
chmod 0644 "$AGENT"
plutil -lint "$AGENT"

"$SOURCE_ROOT/scripts/build-macos-app.sh" "$SOURCE_ROOT/dist" >/dev/null
if [[ ! -d "$(dirname "$APP_DESTINATION")" ]]; then
  install -d -m 0755 "$(dirname "$APP_DESTINATION")"
fi
rm -rf "$APP_DESTINATION"
ditto "$SOURCE_ROOT/dist/Claude Window Starter.app" "$APP_DESTINATION"
codesign --verify --deep --strict "$APP_DESTINATION"

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$AGENT"

python3 -c \
  'import pathlib,shutil,sys; base=pathlib.Path(sys.argv[1]); releases=sorted((p for p in (base/"releases").iterdir() if p.is_dir()),reverse=True); protected={p.resolve() for p in (base/"current",base/"previous") if p.exists()}; [shutil.rmtree(p) for index,p in enumerate(releases) if index>=5 and p.resolve() not in protected]' \
  "$BASE"

echo "Installed: $APP_DESTINATION"
echo "Backend: $BASE/current"
echo "Automation remains disabled until you enable it explicitly."
