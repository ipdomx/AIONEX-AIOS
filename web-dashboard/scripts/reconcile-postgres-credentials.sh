#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $- == *x* ]]; then
  set +x
fi

die() {
  echo "error: $*" >&2
  exit 1
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${COMPOSE_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  die "docker is required"
fi

if ! docker compose version >/dev/null 2>&1; then
  die "Docker Compose v2 is required"
fi

compose_services="$(docker compose config --services)"
grep -qx "postgres" <<<"${compose_services}" ||
  die "the postgres service is missing from the Compose project"
grep -qx "backend" <<<"${compose_services}" ||
  die "the backend service is missing from the Compose project"

echo "Starting PostgreSQL..."
docker compose up -d --no-deps postgres

ready=false
for ((attempt = 1; attempt <= 30; attempt++)); do
  if docker compose exec -T postgres sh -ceu \
    'pg_isready --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" >/dev/null'
  then
    ready=true
    break
  fi
  sleep 2
done

if [[ "${ready}" != "true" ]]; then
  die "PostgreSQL did not become ready within 60 seconds"
fi

echo "Synchronizing the PostgreSQL role password with the container environment..."
docker compose exec -T postgres sh -s <<'CONTAINER_SH'
set -eu
set +x

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"

export PSQLRC=/dev/null

escaped_user="$(printf '%s' "${POSTGRES_USER}" | sed 's/"/""/g')"
escaped_password="$(printf '%s' "${POSTGRES_PASSWORD}" | sed "s/'/''/g")"

printf 'ALTER ROLE "%s" WITH LOGIN PASSWORD '\''%s'\'';\n' \
  "${escaped_user}" "${escaped_password}" |
  psql \
    --no-psqlrc \
    --no-password \
    --username "${POSTGRES_USER}" \
    --dbname "${POSTGRES_DB}" \
    --set ON_ERROR_STOP=1 \
    >/dev/null
CONTAINER_SH

echo "Verifying TCP password authentication..."
docker compose exec -T postgres sh -ceu '
  set +x
  export PSQLRC=/dev/null

  PGPASSWORD="$POSTGRES_PASSWORD" psql \
    --no-psqlrc \
    --no-password \
    --host 127.0.0.1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    --set ON_ERROR_STOP=1 \
    --tuples-only \
    --no-align \
    --command "SELECT 1" \
    | grep -qx "1"
'

echo "Recreating the backend with the synchronized credentials..."
docker compose up -d --force-recreate backend

backend_id="$(docker compose ps -q backend)"
if [[ -z "${backend_id}" ]]; then
  die "Backend container was not created"
fi

healthy=false
for ((attempt = 1; attempt <= 60; attempt++)); do
  backend_state="$(
    docker inspect \
      --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
      "${backend_id}"
  )"
  if [[ "${backend_state}" == "healthy" ]]; then
    healthy=true
    break
  fi
  if [[ "${backend_state}" == "exited" || "${backend_state}" == "dead" ]]; then
    break
  fi
  sleep 2
done

if [[ "${healthy}" != "true" ]]; then
  die "Backend did not become healthy; inspect it with: docker compose logs backend"
fi

echo "PostgreSQL credentials synchronized and backend healthy."
