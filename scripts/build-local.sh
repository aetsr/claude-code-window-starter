#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP="$(mktemp -d "${TMPDIR:-/tmp}/claude-window-starter-build.XXXXXX")"
trap 'rm -rf "$TEMP"' EXIT

PYTHONPATH="$ROOT/backend" python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py'
python3 -m compileall -q "$ROOT/backend"
python3 "$ROOT/scripts/security_scan.py"
python3 -m pip wheel --no-deps --wheel-dir "$TEMP/wheels" "$ROOT"
python3 -m venv "$TEMP/venv"
"$TEMP/venv/bin/pip" install --no-index --find-links "$TEMP/wheels" claude-window-starter==2.1.0
PYTHONPATH="$ROOT/backend" "$TEMP/venv/bin/python" -m claude_starter --home "$TEMP/home" --json version >/dev/null
swift test --package-path "$ROOT/macos-app"
for plist in "$ROOT"/launchd/*.plist; do plutil -lint "$plist" >/dev/null; done
"$ROOT/scripts/build-macos-app.sh" "$ROOT/dist"
echo "Python tests, security scan, wheel install, Swift tests, launchd validation, and signed local app bundle succeeded."
