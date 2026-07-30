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

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
ENV_FILE="${ENV_FILE:-}"
if [[ -z "${ENV_FILE}" ]]; then
  if [[ -f .env.production ]]; then
    ENV_FILE=.env.production
  elif [[ -f .env ]]; then
    ENV_FILE=.env
  else
    die "no .env.production or .env file was found"
  fi
fi
[[ -f "${ENV_FILE}" ]] || die "environment file not found: ${ENV_FILE}"
ENV_FILE="$(realpath "${ENV_FILE}")"

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"

compose_args=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")
compose() {
  AIOS_ENV_FILE="${ENV_FILE}" "${compose_args[@]}" "$@"
}

compose up -d --no-deps postgres
postgres_id="$(compose ps -q postgres)"
[[ -n "${postgres_id}" ]] || die "PostgreSQL container was not created"

for ((attempt = 1; attempt <= 30; attempt++)); do
  if compose exec -T postgres pg_isready --host 127.0.0.1 --port 5432 --quiet; then
    break
  fi
  sleep 2
done

if compose exec -T postgres psql --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" --no-password --command 'SELECT 1' >/dev/null 2>&1; then
  echo "Configured PostgreSQL role already permits local login."
  exit 0
fi

compose stop postgres

recovery_name="${COMPOSE_PROJECT_NAME:-web-dashboard}-postgres-login-recovery"
docker rm -f "${recovery_name}" >/dev/null 2>&1 || true

set +e
docker run --rm \
  --name "${recovery_name}" \
  --user postgres \
  --network none \
  --volumes-from "${postgres_id}" \
  -e TARGET_ROLE="${POSTGRES_USER}" \
  -e TARGET_PASSWORD="${POSTGRES_PASSWORD}" \
  -e TARGET_DATABASE="${POSTGRES_DB}" \
  postgres:16-alpine \
  sh -ceu '
    trap "pg_ctl -D /var/lib/postgresql/data -m fast -w stop >/dev/null 2>&1 || true" EXIT
    pg_ctl -D /var/lib/postgresql/data -o "-c listen_addresses= -c unix_socket_directories=/tmp -c hba_file=/dev/null" -w start
    psql --host /tmp --dbname template1 --set ON_ERROR_STOP=1 \
      --set target_role="$TARGET_ROLE" \
      --set target_password="$TARGET_PASSWORD" \
      --command "SELECT format('"'"'ALTER ROLE %I WITH LOGIN PASSWORD %L'"'"', :'"'"'target_role'"'"', :'"'"'target_password'"'"') \gexec"
  '
recovery_status=$?
set -e

compose up -d --no-deps postgres
if ((recovery_status != 0)); then
  die "offline PostgreSQL login recovery failed"
fi

echo "PostgreSQL login role recovered safely."
