#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-deploy/production/.env.production}"
COMPOSE_FILE="deploy/production/docker-compose.production.yml"

[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE" >&2; exit 1; }
[[ -f "$COMPOSE_FILE" ]] || { echo "Missing $COMPOSE_FILE" >&2; exit 1; }

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config >/dev/null

required=(POSTGRES_PASSWORD SECRET_KEY PUBLIC_ORIGIN API_ORIGIN)
for key in "${required[@]}"; do
  value="$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 | cut -d= -f2-)"
  [[ -n "$value" ]] || { echo "Missing required value: $key" >&2; exit 1; }
done

echo "Production configuration validation passed."
