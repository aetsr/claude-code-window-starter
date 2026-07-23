#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT/dist}"
SHA="$(git -C "$ROOT" rev-parse --verify HEAD)"
ARCHIVE="$OUTPUT/claude-window-starter-bootstrap-${SHA:0:12}.tar"

git -C "$ROOT" diff --quiet
git -C "$ROOT" diff --cached --quiet
install -d -m 0755 "$OUTPUT"
git -C "$ROOT" archive --format=tar --output="$ARCHIVE" "$SHA"
(
  cd "$OUTPUT"
  shasum -a 256 "$(basename "$ARCHIVE")" > "$(basename "$ARCHIVE").sha256"
)

echo "$ARCHIVE"
echo "Commit: $SHA"
