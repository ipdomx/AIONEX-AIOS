#!/usr/bin/env sh
set -eu

ENV_FILE="${AIOS_ENV_FILE:-.env.production}"
COMPOSE_FILE="${AIOS_COMPOSE_FILE:-docker-compose.production.yml}"

fail() {
  printf '%s\n' "ERROR: $*" >&2
  exit 1
}

[ -f "$ENV_FILE" ] || fail "$ENV_FILE is missing"
[ -f "$COMPOSE_FILE" ] || fail "$COMPOSE_FILE is missing"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

[ "${ENVIRONMENT:-production}" = "production" ] || fail "ENVIRONMENT must be production"
[ "${DEBUG:-false}" = "false" ] || fail "DEBUG must be false"
[ -n "${AIOS_ALLOWED_HOSTS:-}" ] || fail "AIOS_ALLOWED_HOSTS is required"
[ -n "${CORS_ORIGINS:-}" ] || fail "CORS_ORIGINS is required"
[ -n "${SECRET_KEY:-}" ] || fail "SECRET_KEY is required"
[ "${#SECRET_KEY}" -ge 32 ] || fail "SECRET_KEY must contain at least 32 characters"

case "${CORS_ORIGINS}" in
  *"*"*) fail "CORS_ORIGINS cannot contain wildcard in production" ;;
esac
case "${AIOS_ALLOWED_HOSTS}" in
  *"*"*) fail "AIOS_ALLOWED_HOSTS cannot contain wildcard in production" ;;
esac

if grep -RInE '(sk-[A-Za-z0-9_-]{20,}|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY|AKIA[0-9A-Z]{16})' . \
  --exclude-dir=node_modules --exclude-dir=.next --exclude-dir=.git --exclude="$ENV_FILE" >/tmp/aionex-secret-scan.txt 2>/dev/null; then
  cat /tmp/aionex-secret-scan.txt >&2
  fail "possible committed secret detected"
fi

if grep -RInE 'productionBrowserSourceMaps:[[:space:]]*true|devtool:[[:space:]]*["'"']source-map' frontend \
  --exclude-dir=node_modules --exclude-dir=.next >/dev/null 2>&1; then
  fail "public production source maps are enabled"
fi

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null
printf '%s\n' "Private-origin preflight passed."
