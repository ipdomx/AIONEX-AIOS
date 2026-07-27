#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT_DIR/deploy/production/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT_DIR/deploy/production/docker-compose.production.yml}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing production environment file: $ENV_FILE" >&2
  exit 1
fi

required_vars=(
  PUBLIC_ORIGIN
  API_ORIGIN
  POSTGRES_DB
  POSTGRES_USER
  POSTGRES_PASSWORD
  SECRET_KEY
)

for var in "${required_vars[@]}"; do
  value="$(grep -E "^${var}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-)"
  if [[ -z "$value" ]]; then
    echo "Missing required variable: $var" >&2
    exit 1
  fi
done

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null

echo "Production configuration validated."
echo "Public origin: https://ai.vip-e.net"
echo "API origin: https://api.ai.vip-e.net"
