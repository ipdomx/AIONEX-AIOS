#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

python -m pytest backend/tests -q

docker compose -f docker-compose.production.yml config >/dev/null

echo "AIONEX AIOS production release verification passed."
