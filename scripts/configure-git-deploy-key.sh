#!/usr/bin/env bash
set -euo pipefail
umask 077

OFFICIAL_GITHUB_ED25519="SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU"
expected="${1:-$OFFICIAL_GITHUB_ED25519}"
if [[ "$expected" == "--stdin" ]]; then
  IFS= read -r expected
fi

BASE="${CLAUDE_STARTER_HOME:-$HOME/.local/share/claude-window-starter}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS="$BASE/shared/secrets"
CONFIG="$BASE/shared/config"
key="$SECRETS/git_deploy_ed25519"
known_hosts="$CONFIG/git_known_hosts"
mkdir -p "$SECRETS" "$CONFIG"

if [[ ! -f "$key" ]]; then
  ssh-keygen -q -t ed25519 -N '' -C 'claude-window-starter read-only deploy key' -f "$key"
fi
chmod 0600 "$key"
chmod 0644 "$key.pub"

scan="$(mktemp)"
trap 'rm -f "$scan"' EXIT
ssh-keyscan -t ed25519 github.com > "$scan" 2>/dev/null
fingerprint="$(ssh-keygen -lf "$scan" -E sha256 | awk '{print $2}' | head -n 1)"
if [[ "$fingerprint" != "$expected" ]]; then
  echo "GitHub host fingerprint mismatch; known_hosts was not changed." >&2
  exit 4
fi
install -m 0600 "$scan" "$known_hosts"

{
  printf '%s\n' \
    'Host github.com' \
    '  HostName github.com' \
    '  User git' \
    "  IdentityFile $key" \
    '  IdentitiesOnly yes' \
    "  UserKnownHostsFile $known_hosts" \
    '  StrictHostKeyChecking yes' \
    '  BatchMode yes'
} > "$CONFIG/git_ssh_config"
chmod 0600 "$CONFIG/git_ssh_config"
install -m 0700 "$SCRIPT_DIR/git-ssh-wrapper.sh" "$CONFIG/git-ssh-wrapper"

echo "GitHub host key verified: $fingerprint"
echo "Add only this public key to the private repository as a read-only deploy key:"
sed -n '1p' "$key.pub"
