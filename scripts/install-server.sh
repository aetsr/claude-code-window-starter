#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo scripts/install-server.sh" >&2
  exit 2
fi

SERVICE_USER="claude-starter"
SERVICE_HOME="/var/lib/claude-starter"
APP_BASE="$SERVICE_HOME/.local/share/claude-window-starter"
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_SHA="${1:-}"

"$SOURCE_ROOT/scripts/diagnose-server.sh"

arch="$(uname -m)"
case "$arch" in
  aarch64|arm64|x86_64) ;;
  *) echo "Unsupported architecture: $arch" >&2; exit 2 ;;
esac

uname -m
lscpu
free -h
cat /etc/os-release
df -h

for command in git python3 systemctl loginctl; do
  command -v "$command" >/dev/null || { echo "Missing required command: $command" >&2; exit 2; }
done

if ! command -v claude >/dev/null 2>&1; then
  command -v curl >/dev/null || { echo "curl is required to configure the official Claude repository" >&2; exit 2; }
  command -v gpg >/dev/null || { echo "gpg is required to verify the Claude signing key" >&2; exit 2; }
  install -d -m 0755 /etc/apt/keyrings
  key_tmp="$(mktemp)"
  trap 'rm -f "$key_tmp"' EXIT
  curl -fsSL https://downloads.claude.ai/keys/claude-code.asc -o "$key_tmp"
  fingerprint="$(gpg --show-keys --with-colons "$key_tmp" | awk -F: '$1=="fpr" {print $10; exit}')"
  if [[ "$fingerprint" != "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE" ]]; then
    echo "Claude package signing-key fingerprint mismatch" >&2
    exit 3
  fi
  install -m 0644 "$key_tmp" /etc/apt/keyrings/claude-code.asc
  printf '%s\n' 'deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main' \
    > /etc/apt/sources.list.d/claude-code.list
  apt-get update
  apt-get install -y claude-code
fi

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
  echo "Python 3.10+ is required. No third-party PPA will be added automatically." >&2
  exit 2
}

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --create-home --home-dir "$SERVICE_HOME" --shell /usr/sbin/nologin "$SERVICE_USER"
fi
usermod --shell /usr/sbin/nologin "$SERVICE_USER"
passwd --lock "$SERVICE_USER" >/dev/null

uid="$(id -u "$SERVICE_USER")"
loginctl enable-linger "$SERVICE_USER"
install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" \
  "$APP_BASE/releases" "$APP_BASE/shared/config" "$APP_BASE/shared/secrets" \
  "$APP_BASE/shared/state" "$APP_BASE/shared/logs" "$APP_BASE/shared/runtime" \
  "$SERVICE_HOME/.config/systemd/user"

if [[ ! -f "$APP_BASE/shared/config/config.json" ]]; then
  install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" \
    "$SOURCE_ROOT/config/config.example.json" "$APP_BASE/shared/config/config.json"
fi

if git -C "$SOURCE_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  sha="$(git -C "$SOURCE_ROOT" rev-parse HEAD)"
  source_is_git=true
elif [[ "$SOURCE_SHA" =~ ^[0-9a-f]{40,64}$ ]]; then
  sha="$SOURCE_SHA"
  source_is_git=false
else
  echo "Run from a Git checkout or pass the trusted source commit SHA as the first argument." >&2
  exit 2
fi
release="$APP_BASE/releases/initial-${sha:0:12}"
if [[ ! -d "$release" ]]; then
  install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$release"
  if [[ "$source_is_git" == true ]]; then
    git -C "$SOURCE_ROOT" archive "$sha" | runuser -u "$SERVICE_USER" -- tar -x -C "$release"
  else
    tar -C "$SOURCE_ROOT" --exclude='.git' --exclude='shared' -cf - . | runuser -u "$SERVICE_USER" -- tar -x -C "$release"
  fi
  chown -R "$SERVICE_USER:$SERVICE_USER" "$release"
  runuser -u "$SERVICE_USER" -- python3 -m venv "$release/.venv"
  runuser -u "$SERVICE_USER" -- "$release/.venv/bin/python" -c \
    'import pathlib,site,sys; pathlib.Path(site.getsitepackages()[0], "claude_window_starter.pth").write_text(sys.argv[1] + "\n")' \
    "$release/backend"
  runuser -u "$SERVICE_USER" -- env PYTHONPATH="$release/backend" \
    "$release/.venv/bin/python" -m unittest discover -s "$release/tests" -p 'test_*.py'
  runuser -u "$SERVICE_USER" -- env CLAUDE_STARTER_HOME="$APP_BASE" \
    "$release/.venv/bin/python" -m claude_starter --home "$APP_BASE" --json health --no-services >/dev/null
  runuser -u "$SERVICE_USER" -- "$release/.venv/bin/python" -c \
    'import hashlib,json,pathlib,platform,sys; lock=pathlib.Path(sys.argv[3]); pathlib.Path(sys.argv[1]).write_text(json.dumps({"schema_version":1,"application_version":"1.0.0","commit_sha":sys.argv[2],"short_commit_sha":sys.argv[2][:12],"branch":"main","build_time":None,"deploy_time":None,"python_version":platform.python_version(),"dependency_lock_hash":hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else None,"deploy_result":"initial","health_check_result":"passed","healthy":True},indent=2)+"\n")' \
    "$release/release.json" "$sha" "$release/requirements-runtime.lock"
fi

if [[ -L "$APP_BASE/current" ]]; then
  old_current="$(readlink -f "$APP_BASE/current")"
  ln -s "$old_current" "$APP_BASE/.previous-new"
  mv -Tf "$APP_BASE/.previous-new" "$APP_BASE/previous"
fi
ln -s "$release" "$APP_BASE/.current-new"
mv -Tf "$APP_BASE/.current-new" "$APP_BASE/current"
chown -h "$SERVICE_USER:$SERVICE_USER" "$APP_BASE/current"

for secret in claude_oauth_token telegram_token; do
  if [[ ! -e "$APP_BASE/shared/secrets/$secret" ]]; then
    install -m 0600 -o "$SERVICE_USER" -g "$SERVICE_USER" /dev/null "$APP_BASE/shared/secrets/$secret"
  fi
done

install -m 0644 -o "$SERVICE_USER" -g "$SERVICE_USER" "$SOURCE_ROOT"/systemd/* "$SERVICE_HOME/.config/systemd/user/"
chmod 0755 "$release"/scripts/*.sh
chown -R "$SERVICE_USER:$SERVICE_USER" "$SERVICE_HOME/.config" "$APP_BASE"

run_user_systemctl() {
  runuser -u "$SERVICE_USER" -- env XDG_RUNTIME_DIR="/run/user/$uid" systemctl --user "$@"
}

runuser -u "$SERVICE_USER" -- env \
  CLAUDE_STARTER_HOME="$APP_BASE" PYTHONPATH="$release/backend" \
  "$release/.venv/bin/python" -m claude_starter schedule --apply-systemd --json
run_user_systemctl daemon-reload
run_user_systemctl enable --now claude-window-starter-run.timer

runuser -u "$SERVICE_USER" -- env CLAUDE_STARTER_HOME="$APP_BASE" \
  "$release/scripts/configure-git-deploy-key.sh"

echo "Installed safely at $APP_BASE"
echo "Automation remains disabled until config and OAuth credentials are supplied."
echo "Add the public deploy key printed above to the private GitHub repository without write access."
