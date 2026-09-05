#!/usr/bin/env bash
# Complete installer archive: compiled app + backend + user-service installer.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT/dist/releases}"
mkdir -p "$OUTPUT"
OUTPUT="$(cd "$OUTPUT" && pwd)"
VERSION="$(PYTHONPATH="$ROOT/backend" python3 -c 'from claude_starter import __version__; print(__version__)')"
STAGING="$(mktemp -d "${TMPDIR:-/tmp}/cws-distribution.XXXXXX")"
trap 'rm -rf "$STAGING"' EXIT
"$ROOT/scripts/build-macos-app.sh" "$STAGING/build"
if [[ -n "${CLAUDE_STARTER_NOTARY_KEY_PATH:-}" ]]; then
  : "${APPLE_API_KEY_ID:?Missing notarization key ID}"
  : "${APPLE_API_ISSUER_ID:?Missing notarization issuer ID}"
  ditto -c -k --sequesterRsrc --keepParent "$STAGING/build/Claude Window Starter.app" "$STAGING/notary.zip"
  xcrun notarytool submit "$STAGING/notary.zip" --key "$CLAUDE_STARTER_NOTARY_KEY_PATH" \
    --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER_ID" --wait --output-format json > "$STAGING/notary-result.json"
  python3 -c 'import json,sys; result=json.load(open(sys.argv[1])); sys.exit(0 if result.get("status")=="Accepted" else "Notarization was not accepted")' "$STAGING/notary-result.json"
  xcrun stapler staple "$STAGING/build/Claude Window Starter.app"
  xcrun stapler validate "$STAGING/build/Claude Window Starter.app"
fi
PACKAGE_NAME="claude-code-window-starter-$VERSION-macos-$(uname -m)-installer"
PACKAGE="$STAGING/$PACKAGE_NAME"
mkdir -p "$PACKAGE/payload" "$PACKAGE/scripts"
ditto "$STAGING/build/Claude Window Starter.app" "$PACKAGE/payload/Claude Window Starter.app"
ditto "$ROOT/backend" "$PACKAGE/backend"
ditto "$ROOT/config" "$PACKAGE/config"
ditto "$ROOT/launchd" "$PACKAGE/launchd"
for script in install-macos.sh uninstall-macos.sh list-releases.sh rollback.sh; do
  install -m 0755 "$ROOT/scripts/$script" "$PACKAGE/scripts/$script"
done
install -m 0755 "$ROOT/scripts/Install.command" "$PACKAGE/Install.command"
install -m 0644 "$ROOT/docs/INSTALLER.md" "$PACKAGE/INSTALL.md"
install -m 0644 "$ROOT/LICENSE" "$PACKAGE/LICENSE"
# Exclude interpreter caches from distributed backend sources.
find "$PACKAGE/backend" -type d -name __pycache__ -prune -exec rm -rf {} +
ditto -c -k --sequesterRsrc --keepParent "$PACKAGE" "$OUTPUT/$PACKAGE_NAME.zip"
(cd "$OUTPUT" && shasum -a 256 "$PACKAGE_NAME.zip" > "$PACKAGE_NAME.zip.sha256")
echo "Installer archive: $OUTPUT/$PACKAGE_NAME.zip"
