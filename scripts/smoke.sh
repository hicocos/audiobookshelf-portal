#!/usr/bin/env bash
set -euo pipefail

PORTAL_URL="${PORTAL_URL:-https://moyin.cc}"
API_URL="${API_URL:-http://127.0.0.1:8019}"
ABS_URL="${ABS_URL:-https://listen.moyin.cc}"
RANGE_PATH="${RANGE_PATH:-}"

check_status() {
  local name="$1" url="$2" expected="${3:-200}"
  local status
  status="$(curl --fail-with-body --silent --show-error --location --max-time 15 --output /dev/null --write-out '%{http_code}' "$url")"
  [[ "$status" == "$expected" ]] || { printf '%s: expected %s, got %s\n' "$name" "$expected" "$status" >&2; return 1; }
  printf 'ok: %s (%s)\n' "$name" "$status"
}

check_status "Portal" "$PORTAL_URL/"
check_status "API readiness" "$API_URL/api/public/health/ready"
check_status "ABS ping" "$ABS_URL/ping"

if [[ -n "$RANGE_PATH" ]]; then
  headers="$(mktemp)"
  trap 'rm -f "$headers"' EXIT
  status="$(curl --silent --show-error --location --max-time 30 --range 0-31 --dump-header "$headers" --output /dev/null --write-out '%{http_code}' "$ABS_URL$RANGE_PATH")"
  [[ "$status" == "206" ]] || { printf 'Range: expected 206, got %s\n' "$status" >&2; exit 1; }
  grep -iq '^content-range:' "$headers" || { printf 'Range: missing Content-Range\n' >&2; exit 1; }
  printf 'ok: ABS Range (206 + Content-Range)\n'
else
  printf 'skip: ABS Range (set RANGE_PATH to a known media URL path)\n'
fi

printf 'note: WebSocket/Socket.IO 101 requires a valid protocol-specific endpoint and is verified separately during production release.\n'
