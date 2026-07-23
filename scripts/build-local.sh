#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH="$ROOT/backend" python3 -m unittest discover -s "$ROOT/tests" -p 'test_*.py'
python3 -m compileall -q "$ROOT/backend"
swift test --package-path "$ROOT/macos-app"
swift build -c release --package-path "$ROOT/macos-app"
echo "Local backend tests and Swift release build succeeded."
