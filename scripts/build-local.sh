#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP="$(mktemp -d "${TMPDIR:-/tmp}/claude-window-starter-build.XXXXXX")"
trap 'rm -rf "$TEMP"' EXIT

PYTHONPATH="$ROOT/backend" python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py'
python3 -m compileall -q "$ROOT/backend"
python3 -m pip wheel --no-deps --wheel-dir "$TEMP/wheels" "$ROOT"
python3 -m venv "$TEMP/venv"
"$TEMP/venv/bin/pip" install --no-index --find-links "$TEMP/wheels" claude-window-starter==1.0.0
"$TEMP/venv/bin/claude-window-starter" --home "$TEMP/home" --json version >/dev/null
swift test --package-path "$ROOT/macos-app"
"$ROOT/scripts/build-macos-app.sh" "$ROOT/dist"
echo "Backend tests, wheel install, Swift tests, and signed local app bundle succeeded."
