#!/usr/bin/env bash
# CI-only signing bootstrap. Secrets are never written into distribution files.
set -euo pipefail
[[ "${CI:-}" == true ]] || { echo "CI-only script; use an existing signing identity locally." >&2; exit 2; }
: "${MACOS_CERTIFICATE_P12_BASE64:?Developer ID certificate required}"
: "${MACOS_CERTIFICATE_PASSWORD:?Certificate password required}"
: "${DEVELOPER_ID_APPLICATION:?Developer ID signing identity required}"
: "${APPLE_API_KEY_P8:?Notarization key required}"
: "${APPLE_API_KEY_ID:?Notarization key ID required}"
: "${APPLE_API_ISSUER_ID:?Notarization issuer required}"
[[ "$DEVELOPER_ID_APPLICATION" == "Developer ID Application:"* ]] || { echo "Developer ID Application identity required." >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
umask 077
SIGNING_TEMP="$(mktemp -d "${TMPDIR:-/tmp}/cws-signing.XXXXXX")"
KEYCHAIN="$SIGNING_TEMP/signing.keychain-db"
cleanup() {
  security delete-keychain "$KEYCHAIN" >/dev/null 2>&1 || true
  rm -rf "$SIGNING_TEMP"
}
trap cleanup EXIT
KEYCHAIN_PASSWORD="$(openssl rand -hex 32)"
python3 - "$SIGNING_TEMP" <<'PY'
import base64
import os
import pathlib
import sys
root = pathlib.Path(sys.argv[1])
(root / 'identity.p12').write_bytes(base64.b64decode(os.environ['MACOS_CERTIFICATE_P12_BASE64'], validate=True))
(root / 'notary.p8').write_text(os.environ['APPLE_API_KEY_P8'])
PY
security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 21600 "$KEYCHAIN"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN"
security import "$SIGNING_TEMP/identity.p12" -P "$MACOS_CERTIFICATE_PASSWORD" -k "$KEYCHAIN" -T /usr/bin/codesign >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$KEYCHAIN_PASSWORD" "$KEYCHAIN" >/dev/null
# The job runs on a disposable hosted runner; do not modify a developer's search list.
security list-keychains -d user -s "$KEYCHAIN"
CLAUDE_STARTER_SIGN_IDENTITY="$DEVELOPER_ID_APPLICATION" \
CLAUDE_STARTER_NOTARY_KEY_PATH="$SIGNING_TEMP/notary.p8" \
  "$ROOT/scripts/build-distribution.sh" "${1:-$ROOT/dist/releases}"
