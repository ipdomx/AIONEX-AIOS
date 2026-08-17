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
[[ -f "${COMPOSE_FILE}" ]] || die "Compose file not found: ${COMPOSE_FILE}"
ENV_FILE="$(realpath "${ENV_FILE}")"

if ! command -v docker >/dev/null 2>&1; then
  die "docker is required"
fi
if ! docker compose version >/dev/null 2>&1; then
  die "Docker Compose v2 is required"
fi

compose_args=(docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}")
compose() {
  AIOS_ENV_FILE="${ENV_FILE}" "${compose_args[@]}" "$@"
}

compose_environment="$("${compose_args[@]}" config --environment)"
environment_value() {
  local key="$1"
  local line
  line="$(grep -m1 -E "^${key}=" <<<"${compose_environment}" || true)"
  [[ -n "${line}" ]] || return 1
  printf '%s' "${line#*=}"
}

POSTGRES_USER="$(environment_value POSTGRES_USER || true)"
POSTGRES_PASSWORD="$(environment_value POSTGRES_PASSWORD || true)"
POSTGRES_DB="$(environment_value POSTGRES_DB || true)"

[[ -n "${POSTGRES_USER}" ]] || die "POSTGRES_USER is required"
[[ -n "${POSTGRES_PASSWORD}" ]] || die "POSTGRES_PASSWORD is required"
[[ -n "${POSTGRES_DB}" ]] || die "POSTGRES_DB is required"

compose up -d --no-deps postgres
postgres_id="$(compose ps -q postgres)"
[[ -n "${postgres_id}" ]] || die "PostgreSQL container was not created"

ready=false
for ((attempt = 1; attempt <= 30; attempt++)); do
  if compose exec -T postgres pg_isready --host 127.0.0.1 --port 5432 --username "${POSTGRES_USER}" --dbname "${POSTGRES_DB}" --quiet; then
    ready=true
    break
  fi
  sleep 2
done
[[ "${ready}" == "true" ]] || die "PostgreSQL did not become ready within 60 seconds"

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
  postgres:16-alpine \
  sh -ceu '
    command_file="$(mktemp)"
    trap "rm -f \"$command_file\"" EXIT

    escaped_role=$(printf "%s" "$TARGET_ROLE" | sed "s/\"/\"\"/g")
    escaped_password=$(printf "%s" "$TARGET_PASSWORD" | sed "s/'"'"'/''/g")
    printf "ALTER ROLE \"%s\" WITH LOGIN PASSWORD '\''%s'\'';\n" \
      "$escaped_role" \
      "$escaped_password" \
      > "$command_file"

    postgres --single -D /var/lib/postgresql/data template1 < "$command_file"
  '
recovery_status=$?
set -e

compose up -d --no-deps postgres
if ((recovery_status != 0)); then
  die "offline PostgreSQL login recovery failed"
fi

echo "PostgreSQL login role recovered safely."
