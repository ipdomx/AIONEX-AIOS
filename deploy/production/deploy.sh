#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR"

if [ ! -f .env.production ]; then
  echo "Missing deploy/production/.env.production" >&2
  exit 1
fi

export AIOS_ENV_FILE="$SCRIPT_DIR/.env.production"
ENV_FILE="$AIOS_ENV_FILE" \
  COMPOSE_FILE="$SCRIPT_DIR/docker-compose.production.yml" \
  bash "$SCRIPT_DIR/final-release-check.sh"
docker compose -f docker-compose.production.yml --env-file .env.production config >/dev/null
docker compose -f docker-compose.production.yml --env-file .env.production pull --ignore-buildable
docker compose -f docker-compose.production.yml --env-file .env.production build --pull
docker compose -f docker-compose.production.yml --env-file .env.production up -d --remove-orphans
docker compose -f docker-compose.production.yml --env-file .env.production ps
