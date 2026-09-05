#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DESTINATION="${CLAUDE_STARTER_APP_PATH:-/Applications/Claude Window Starter.app}"
if [[ $# -ne 0 ]]; then
  echo "Usage: $0 (set CLAUDE_STARTER_APP_PATH to customize the app destination)" >&2
  exit 2
fi
if [[ "$(uname -s)" != Darwin ]]; then
  echo "This installer requires macOS." >&2
  exit 2
fi
if [[ -e "$SOURCE_ROOT/.git" ]] && [[ -n "$(git -C "$SOURCE_ROOT" status --porcelain --untracked-files=normal)" ]]; then
  echo "Refusing to install from a dirty repository. Commit the production source first." >&2
  exit 2
fi

# Finder's PATH differs from a Terminal shell. Validate an external interpreter
# explicitly; no Xcode or pip is needed when installing a packaged app.
PYTHON=""
for candidate in "${CLAUDE_STARTER_PYTHON:-python3}" /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /usr/local/bin/python3; do
  if "$candidate" -c 'import sys,venv; sys.exit(not ((3,10) <= sys.version_info[:2] <= (3,13)))' 2>/dev/null; then
    PYTHON="$("$candidate" -c 'import sys; print(sys.executable)')"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "Install Python 3.10–3.13 from python.org, then retry. Python is required at runtime." >&2
  echo "You can select it with CLAUDE_STARTER_PYTHON=/absolute/path/to/python3." >&2
  exit 2
fi

APP_SOURCE="$SOURCE_ROOT/payload/Claude Window Starter.app"
if [[ ! -d "$APP_SOURCE" ]]; then
  command -v swift >/dev/null || { echo "Source installation requires Swift 6+. Use an installer ZIP to avoid building." >&2; exit 2; }
  "$SOURCE_ROOT/scripts/build-macos-app.sh" "$SOURCE_ROOT/dist"
  APP_SOURCE="$SOURCE_ROOT/dist/Claude Window Starter.app"
fi
PYTHONPATH="$SOURCE_ROOT/backend" "$PYTHON" -m claude_starter.installation \
  --source "$SOURCE_ROOT" --app "$APP_SOURCE" --app-destination "$APP_DESTINATION"
echo "Installed: $APP_DESTINATION"
echo "Existing automation and Telegram preferences were preserved."
open "$APP_DESTINATION"
