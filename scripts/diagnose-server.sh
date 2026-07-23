#!/usr/bin/env bash
set -uo pipefail

failures=0
warnings=0

pass() { printf 'PASS  %s\n' "$1"; }
warn() { printf 'WARN  %s\n' "$1"; warnings=$((warnings + 1)); }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

printf 'Claude Window Starter server preflight\n'
printf '======================================\n'

arch="$(uname -m 2>/dev/null || true)"
case "$arch" in
  aarch64|arm64|x86_64) pass "architecture: $arch" ;;
  *) fail "unsupported architecture: ${arch:-unknown}" ;;
esac

if [[ -r /etc/os-release ]]; then
  os_id="$(. /etc/os-release; printf '%s' "${ID:-unknown}")"
  os_version="$(. /etc/os-release; printf '%s' "${VERSION_ID:-unknown}")"
  if [[ "$os_id" == "ubuntu" || "$os_id" == "debian" ]]; then
    pass "operating system: $os_id $os_version"
  else
    fail "Ubuntu or Debian is required; found $os_id $os_version"
  fi
else
  fail "/etc/os-release is unavailable"
fi

if command -v lscpu >/dev/null 2>&1; then
  lscpu | sed -n '1,12p'
else
  warn "lscpu is unavailable"
fi
if command -v free >/dev/null 2>&1; then
  free -h
  memory_kib="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || true)"
  if [[ "$memory_kib" =~ ^[0-9]+$ ]] && (( memory_kib >= 4 * 1024 * 1024 )); then
    pass "memory is at least 4 GiB"
  else
    fail "Claude Code requires at least 4 GiB RAM"
  fi
else
  warn "free is unavailable"
fi
df -h "${TMPDIR:-/tmp}" 2>/dev/null || fail "disk information is unavailable"
disk_kib="$(df -Pk "${TMPDIR:-/tmp}" 2>/dev/null | awk 'NR==2 {print $4}')"
if [[ "$disk_kib" =~ ^[0-9]+$ ]] && (( disk_kib >= 2 * 1024 * 1024 )); then
  pass "free disk is at least 2 GiB"
else
  fail "at least 2 GiB free disk is required"
fi

if command -v python3 >/dev/null 2>&1 && python3 -c \
  'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 13) else 1)' \
  >/dev/null 2>&1; then
  pass "python: $(python3 --version 2>&1)"
else
  fail "Python 3.10-3.13 is required"
fi
if python3 -m venv --help >/dev/null 2>&1; then
  pass "Python venv support"
else
  fail "python3-venv is required"
fi

if command -v systemctl >/dev/null 2>&1 && [[ "$(ps -p 1 -o comm= 2>/dev/null)" == "systemd" ]]; then
  pass "systemd: $(systemctl --version | head -n 1)"
else
  fail "systemd is not running as PID 1"
fi

for command in git curl gpg ssh ssh-keygen; do
  if command -v "$command" >/dev/null 2>&1; then
    pass "command available: $command"
  else
    fail "required command missing: $command"
  fi
done

for host in api.anthropic.com downloads.claude.ai github.com api.telegram.org; do
  if getent ahosts "$host" >/dev/null 2>&1; then
    pass "DNS: $host"
  else
    fail "DNS lookup failed: $host"
  fi
done

for url in https://api.anthropic.com https://downloads.claude.ai https://github.com https://api.telegram.org; do
  if curl --proto '=https' --tlsv1.2 -sSI --max-time 15 "$url" >/dev/null 2>&1; then
    pass "HTTPS: $url"
  else
    fail "HTTPS unavailable: $url"
  fi
done

if command -v claude >/dev/null 2>&1; then
  pass "Claude Code: $(claude --version 2>&1 | head -n 1)"
  if claude --help >/dev/null 2>&1; then
    pass "Claude Code help is readable"
  else
    fail "Claude Code help failed"
  fi
  if claude auth status --json >/dev/null 2>&1; then
    pass "Claude auth command succeeded"
  else
    warn "Claude auth is not configured for the current diagnostic user"
  fi
else
  warn "Claude Code is absent and will be installed from the verified stable APT repository"
fi

if git ls-remote https://github.com/octocat/Hello-World.git HEAD >/dev/null 2>&1; then
  pass "Git outbound access"
else
  fail "Git cannot reach GitHub over HTTPS"
fi

printf '--------------------------------------\n'
printf 'Preflight result: %d failure(s), %d warning(s)\n' "$failures" "$warnings"
if (( failures > 0 )); then
  exit 2
fi
