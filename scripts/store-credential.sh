#!/usr/bin/env bash
set -euo pipefail
umask 077

name="${1:-}"
case "$name" in
  claude_oauth_token|telegram_token) ;;
  *) echo "Unsupported credential name" >&2; exit 2 ;;
esac

BASE="${CLAUDE_STARTER_HOME:-$HOME/.local/share/claude-window-starter}"
read -r secret
[[ -n "$secret" ]] || { echo "Credential must not be empty" >&2; exit 2; }
mkdir -p "$BASE/shared/secrets" "$HOME/.config/systemd/user"

encrypted="$BASE/shared/secrets/$name.cred"
plain="$BASE/shared/secrets/$name"
used_encrypted=false
if command -v systemd-creds >/dev/null 2>&1 && systemd-creds encrypt --help 2>&1 | grep -q -- '--user'; then
  if printf '%s' "$secret" | systemd-creds encrypt --user --name="$name" - "$encrypted" >/dev/null 2>&1; then
    chmod 0600 "$encrypted"
    used_encrypted=true
  fi
fi

if [[ "$used_encrypted" == false ]]; then
  printf '%s' "$secret" > "$plain"
  chmod 0600 "$plain"
fi
unset secret

units=()
if [[ "$name" == "claude_oauth_token" ]]; then
  units+=("claude-window-starter-run@.service")
else
  units+=("claude-window-starter-telegram.service" "claude-window-starter-deploy.service")
fi

if [[ "$used_encrypted" == true ]]; then
  for unit in "${units[@]}"; do
    dropin="$HOME/.config/systemd/user/$unit.d"
    mkdir -p "$dropin"
    {
      printf '[Service]\nLoadCredential=\n'
      printf 'LoadCredentialEncrypted=%s:%s\n' "$name" "$encrypted"
    } > "$dropin/credential.conf"
    chmod 0600 "$dropin/credential.conf"
  done
fi
systemctl --user daemon-reload >/dev/null 2>&1 || true
echo "$name configured securely; its value was not displayed."
