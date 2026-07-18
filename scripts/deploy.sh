#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE_DIR="$ROOT_DIR/deploy/env"
RUNTIME_FILES=(.env .env.api .env.worker .env.bot)

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy.sh <init|check|up|status|smoke>

  init    Create service-scoped environment files with generated secrets.
  check   Validate configuration, placeholders, permissions, and Compose.
  up      Validate, build all images once, and start the complete stack.
  status  Show Compose service and health state.
  smoke   Run HTTP smoke checks (override PORTAL_URL/ABS_URL if needed).

Optional init environment variables:
  PORTAL_PUBLIC_URL_INIT, ABS_ADMIN_TOKEN, TELEGRAM_BOT_TOKEN,
  TELEGRAM_BOT_USERNAME
EOF
}

random_secret() {
  openssl rand -hex 32
}

escape_replacement() {
  sed 's/[&|\\]/\\&/g' <<<"$1"
}

render() {
  local source="$1" destination="$2"
  shift 2
  local expressions=() key value
  while (($#)); do
    key="$1"
    value="$(escape_replacement "$2")"
    expressions+=("-e" "s|__${key}__|${value}|g")
    shift 2
  done
  sed "${expressions[@]}" "$source" >"$destination"
  chmod 0600 "$destination"
}

init_config() {
  local file
  for file in "${RUNTIME_FILES[@]}"; do
    if [[ -e "$ROOT_DIR/$file" ]]; then
      printf 'refusing to overwrite existing %s\n' "$file" >&2
      return 1
    fi
  done
  command -v openssl >/dev/null || { printf 'missing required command: openssl\n' >&2; return 1; }

  local portal_url="${PORTAL_PUBLIC_URL_INIT:-https://portal.example.com}"
  local abs_token="${ABS_ADMIN_TOKEN:-CHANGE_ME_ABS_ADMIN_TOKEN}"
  local bot_token="${TELEGRAM_BOT_TOKEN:-CHANGE_ME_TELEGRAM_BOT_TOKEN}"
  local bot_username="${TELEGRAM_BOT_USERNAME:-}"
  local jwt_secret internal_token admin_setup_token metrics_token
  jwt_secret="$(random_secret)"
  internal_token="$(random_secret)"
  admin_setup_token="$(random_secret)"
  metrics_token="$(random_secret)"

  umask 077
  render "$TEMPLATE_DIR/compose.env.example" "$ROOT_DIR/.env" \
    PORTAL_PUBLIC_URL "$portal_url"
  render "$TEMPLATE_DIR/api.env.example" "$ROOT_DIR/.env.api" \
    PORTAL_PUBLIC_URL "$portal_url" ABS_ADMIN_TOKEN "$abs_token" \
    JWT_SECRET "$jwt_secret" TELEGRAM_BOT_USERNAME "$bot_username" \
    INTERNAL_TOKEN "$internal_token" ADMIN_SETUP_TOKEN "$admin_setup_token" \
    METRICS_TOKEN "$metrics_token"
  render "$TEMPLATE_DIR/worker.env.example" "$ROOT_DIR/.env.worker" \
    ABS_ADMIN_TOKEN "$abs_token"
  render "$TEMPLATE_DIR/bot.env.example" "$ROOT_DIR/.env.bot" \
    TELEGRAM_BOT_TOKEN "$bot_token" TELEGRAM_BOT_USERNAME "$bot_username" \
    INTERNAL_TOKEN "$internal_token" PORTAL_PUBLIC_URL "$portal_url"

  printf 'created .env, .env.api, .env.worker, and .env.bot with mode 0600\n'
  printf 'edit CHANGE_ME values and public URLs, then run: ./scripts/deploy.sh check\n'
}

check_config() {
  command -v docker >/dev/null || { printf 'missing required command: docker\n' >&2; return 1; }
  docker compose version >/dev/null

  local file mode failed=0
  for file in "${RUNTIME_FILES[@]}"; do
    if [[ ! -f "$ROOT_DIR/$file" ]]; then
      printf 'missing: %s (run ./scripts/deploy.sh init)\n' "$file" >&2
      failed=1
      continue
    fi
    mode="$(stat -c '%a' "$ROOT_DIR/$file")"
    if [[ "$mode" != "600" ]]; then
      printf 'unsafe permissions: %s is %s, expected 600\n' "$file" "$mode" >&2
      failed=1
    fi
    if grep -Eq '(^|=)(CHANGE_ME|replace-with-|https://portal\.example\.com)|__[A-Z0-9_]+__' "$ROOT_DIR/$file"; then
      printf 'unresolved placeholder: %s\n' "$file" >&2
      failed=1
    fi
  done
  ((failed == 0)) || return 1
  (cd "$ROOT_DIR" && docker compose config -q)
  printf 'configuration ok\n'
}

start_stack() {
  check_config
  export BUILD_VERSION="${BUILD_VERSION:-$(date -u +%Y%m%d-%H%M%S)}"
  export BUILD_COMMIT="${BUILD_COMMIT:-$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD 2>/dev/null || printf unknown)}"
  export BUILD_DATE="${BUILD_DATE:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
  (cd "$ROOT_DIR" && docker compose up -d --build)
  (cd "$ROOT_DIR" && docker compose ps)
}

case "${1:-}" in
  init) init_config ;;
  check) check_config ;;
  up) start_stack ;;
  status) (cd "$ROOT_DIR" && docker compose ps) ;;
  smoke) (cd "$ROOT_DIR" && ./scripts/smoke.sh) ;;
  *) usage; exit 2 ;;
esac
