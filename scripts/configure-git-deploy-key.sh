#!/usr/bin/env bash
set -euo pipefail
umask 077

expected="${1:-}"
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
echo "Add this public key to GitHub as a read-only deploy key:"
cat "$key.pub"

scan="$(mktemp)"
trap 'rm -f "$scan"' EXIT
ssh-keyscan -t ed25519 github.com > "$scan" 2>/dev/null
fingerprint="$(ssh-keygen -lf "$scan" -E sha256 | awk '{print $2}' | head -n 1)"
echo "Observed github.com ED25519 fingerprint: $fingerprint"
if [[ -z "$expected" ]]; then
  echo "Compare it with GitHub's published fingerprint, then rerun with that SHA256 fingerprint." >&2
  exit 3
fi
if [[ "$fingerprint" != "$expected" ]]; then
  echo "Fingerprint mismatch; known_hosts was not changed." >&2
  exit 4
fi
install -m 0600 "$scan" "$known_hosts"

cat > "$CONFIG/git_ssh_config" <<EOF
Host github.com
  HostName github.com
  User git
  IdentityFile $key
  IdentitiesOnly yes
  UserKnownHostsFile $known_hosts
  StrictHostKeyChecking yes
  BatchMode yes
EOF
chmod 0600 "$CONFIG/git_ssh_config"
if [[ -f "$SCRIPT_DIR/git-ssh-wrapper.sh" ]]; then
  install -m 0700 "$SCRIPT_DIR/git-ssh-wrapper.sh" "$CONFIG/git-ssh-wrapper"
else
  {
    printf '%s\n' '#!/bin/sh' 'set -eu'
    printf '%s\n' 'BASE="${CLAUDE_STARTER_HOME:-$HOME/.local/share/claude-window-starter}"'
    printf '%s\n' 'exec /usr/bin/ssh -F "$BASE/shared/config/git_ssh_config" "$@"'
  } > "$CONFIG/git-ssh-wrapper"
  chmod 0700 "$CONFIG/git-ssh-wrapper"
fi
echo "Host key pinned. Add the key to GitHub, configure repository_url, then run check-update.sh."
