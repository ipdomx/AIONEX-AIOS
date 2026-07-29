#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/deploy/production/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/deploy/production/docker-compose.production.yml}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing production environment file: $ENV_FILE" >&2
  exit 1
fi
if [[ ! -f "$COMPOSE_FILE" ]]; then
  echo "Missing production Compose file: $COMPOSE_FILE" >&2
  exit 1
fi
ENV_FILE="$(realpath "$ENV_FILE")"
COMPOSE_FILE="$(realpath "$COMPOSE_FILE")"

required_vars=(
  PUBLIC_DOMAIN
  API_DOMAIN
  PUBLIC_ORIGIN
  API_ORIGIN
  CORS_ORIGINS
  POSTGRES_DB
  POSTGRES_USER
  POSTGRES_PASSWORD
  SECRET_KEY
)

read_value() {
  sed -n "s/^${1}=//p" "$ENV_FILE" | tail -n1
}

for var in "${required_vars[@]}"; do
  value="$(read_value "$var")"
  if [[ -z "$value" ]]; then
    echo "Missing required variable: $var" >&2
    exit 1
  fi
done

public_domain="$(read_value PUBLIC_DOMAIN)"
api_domain="$(read_value API_DOMAIN)"
public_origin="$(read_value PUBLIC_ORIGIN)"
api_origin="$(read_value API_ORIGIN)"
cors_origins="$(read_value CORS_ORIGINS)"
postgres_password="$(read_value POSTGRES_PASSWORD)"
secret_key="$(read_value SECRET_KEY)"
bootstrap_owner_password="$(read_value AIOS_BOOTSTRAP_OWNER_PASSWORD)"

[[ "$public_origin" == "https://${public_domain}" ]] || {
  echo "PUBLIC_ORIGIN must equal https://PUBLIC_DOMAIN" >&2
  exit 1
}
[[ "$api_origin" == "https://${api_domain}" ]] || {
  echo "API_ORIGIN must equal https://API_DOMAIN" >&2
  exit 1
}
[[ "$cors_origins" == *"\"${public_origin}\""* ]] || {
  echo "CORS_ORIGINS must include PUBLIC_ORIGIN as a JSON string" >&2
  exit 1
}
[[ "$postgres_password" != CHANGE_ME* ]] || {
  echo "POSTGRES_PASSWORD must be replaced before deployment" >&2
  exit 1
}
[[ "$secret_key" != CHANGE_ME* && ${#secret_key} -ge 32 ]] || {
  echo "SECRET_KEY must be replaced with at least 32 characters" >&2
  exit 1
}
[[ -z "$bootstrap_owner_password" || (
  "$bootstrap_owner_password" != CHANGE_ME* &&
  ${#bootstrap_owner_password} -ge 12
) ]] || {
  echo "AIOS_BOOTSTRAP_OWNER_PASSWORD must be replaced with at least 12 characters" >&2
  exit 1
}

AIOS_ENV_FILE="$ENV_FILE" \
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null

echo "Production configuration validated."
