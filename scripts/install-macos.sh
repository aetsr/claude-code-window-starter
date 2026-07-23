#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$HOME/Library/Application Support/ClaudeWindowStarter"
release="$BASE/releases/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$release" "$BASE/shared/config" "$BASE/shared/state" "$BASE/shared/logs" "$BASE/shared/runtime" "$BASE/shared/secrets"
ditto "$SOURCE_ROOT/backend" "$release/backend"
python3 -m venv "$release/.venv"
"$release/.venv/bin/python" -c \
  'import pathlib,site,sys; pathlib.Path(site.getsitepackages()[0], "claude_window_starter.pth").write_text(sys.argv[1] + "\n")' \
  "$release/backend"
ln -sfn "$release" "$BASE/.current-new"
mv -f "$BASE/.current-new" "$BASE/current"
if [[ ! -f "$BASE/shared/config/config.json" ]]; then
  install -m 0600 "$SOURCE_ROOT/config/config.example.json" "$BASE/shared/config/config.json"
  "$release/.venv/bin/python" -m claude_starter --home "$BASE" config set execution_mode '"this_mac"' >/dev/null
fi

agent="$HOME/Library/LaunchAgents/com.openai.claude-window-starter.plist"
mkdir -p "$(dirname "$agent")"
python3 -c \
  'import pathlib,sys; t=pathlib.Path(sys.argv[1]).read_text(); values={"@@PYTHON@@":sys.argv[3],"@@HOME@@":sys.argv[4],"@@BACKEND@@":sys.argv[5]}; [None for k,v in values.items() if not (t:=t.replace(k,v))]; pathlib.Path(sys.argv[2]).write_text(t)' \
  "$SOURCE_ROOT/launchd/com.openai.claude-window-starter.plist" "$agent" \
  "$release/.venv/bin/python" "$BASE" "$release/backend"
plutil -lint "$agent"
launchctl bootout "gui/$(id -u)/com.openai.claude-window-starter" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$agent"
echo "Installed local backend and launchd agent. Automation remains disabled."
