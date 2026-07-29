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

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
ENV_FILE="${ENV_FILE:-}"

[[ -f "${COMPOSE_FILE}" ]] ||
  die "Compose file not found: ${COMPOSE_FILE}"
if [[ -n "${ENV_FILE}" && ! -f "${ENV_FILE}" ]]; then
  die "environment file not found: ${ENV_FILE}"
fi
if [[ -n "${ENV_FILE}" ]]; then
  ENV_FILE="$(realpath "${ENV_FILE}")"
fi

if ! command -v docker >/dev/null 2>&1; then
  die "docker is required"
fi

if ! docker compose version >/dev/null 2>&1; then
  die "Docker Compose v2 is required"
fi

compose_args=(-f "${COMPOSE_FILE}")
if [[ -n "${ENV_FILE}" ]]; then
  compose_args+=(--env-file "${ENV_FILE}")
fi

compose() {
  if [[ -n "${ENV_FILE}" ]]; then
    AIOS_ENV_FILE="${ENV_FILE}" docker compose "${compose_args[@]}" "$@"
  else
    docker compose "${compose_args[@]}" "$@"
  fi
}

backup_worker_stopped=false
credentials_changed=false

cleanup() {
  exit_code=$?
  set +e
  if [[ "${backup_worker_stopped}" == "true" ]]; then
    if [[ "${credentials_changed}" == "true" ]]; then
      compose up -d --no-deps --force-recreate backup-worker >/dev/null
    else
      compose start backup-worker >/dev/null
    fi
  fi
  trap - EXIT
  exit "${exit_code}"
}
trap cleanup EXIT

running_recovery_job_count() {
  compose exec -T postgres sh -ceu \
    'psql --no-psqlrc --no-password --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 --tuples-only --no-align --quiet' <<'SQL'
CREATE TEMP TABLE aios_active_recovery_jobs (job_count bigint NOT NULL);
DO $aionex$
DECLARE
  relation regclass;
  relation_count bigint;
  total bigint := 0;
BEGIN
  relation := to_regclass('backup_records');
  IF relation IS NOT NULL THEN
    EXECUTE format(
      'SELECT count(*) FROM %s WHERE status = %L',
      relation,
      'running'
    ) INTO relation_count;
    total := total + relation_count;
  END IF;

  relation := to_regclass('disaster_recovery_runs');
  IF relation IS NOT NULL THEN
    EXECUTE format(
      'SELECT count(*) FROM %s WHERE status = %L',
      relation,
      'running'
    ) INTO relation_count;
    total := total + relation_count;
  END IF;

  INSERT INTO aios_active_recovery_jobs (job_count) VALUES (total);
END;
$aionex$;
SELECT job_count FROM aios_active_recovery_jobs;
SQL
}

compose_services="$(compose config --services)"
grep -qx "postgres" <<<"${compose_services}" ||
  die "the postgres service is missing from the Compose project"
grep -qx "backend" <<<"${compose_services}" ||
  die "the backend service is missing from the Compose project"
has_backup_worker=false
if grep -qx "backup-worker" <<<"${compose_services}"; then
  has_backup_worker=true
fi

resolved_database_url="$(
  compose config --environment |
    sed -n 's/^DATABASE_URL=//p' |
    tail -n 1
)"
if [[ -n "${resolved_database_url}" ]]; then
  die "backend DATABASE_URL is explicitly set; reconcile only the bundled PostgreSQL service through POSTGRES_*"
fi

echo "Starting PostgreSQL..."
compose up -d --no-deps postgres

ready=false
for ((attempt = 1; attempt <= 30; attempt++)); do
  if compose exec -T postgres sh -ceu \
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

if [[ "${has_backup_worker}" == "true" ]] &&
  [[ -n "$(compose ps --status running -q backup-worker)" ]]; then
  echo "Stopping the backup worker before changing database credentials..."
  backup_worker_stopped=true
  compose stop backup-worker
fi

running_job_count="$(
  running_recovery_job_count |
    tr -d '[:space:]'
)"
[[ "${running_job_count}" =~ ^[[:digit:]]+$ ]] ||
  die "could not verify active backup and restore jobs"
if ((running_job_count > 0)); then
  die "credential reconciliation refused because a backup or restore job remains running"
fi

echo "Synchronizing the PostgreSQL role password with the container environment..."
compose exec -T postgres sh -s <<'CONTAINER_SH'
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
credentials_changed=true

echo "Verifying TCP password authentication..."
compose exec -T postgres sh -ceu '
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
compose up -d --force-recreate backend

backend_id="$(compose ps -q backend)"
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

if [[ "${has_backup_worker}" == "true" ]]; then
  echo "Recreating the backup worker with the synchronized credentials..."
  compose up -d --no-deps --force-recreate backup-worker

  backup_worker_id="$(compose ps -q backup-worker)"
  if [[ -z "${backup_worker_id}" ]]; then
    die "Backup worker container was not created"
  fi

  backup_worker_running=false
  for ((attempt = 1; attempt <= 30; attempt++)); do
    backup_worker_state="$(
      docker inspect \
        --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "${backup_worker_id}"
    )"
    if [[ "${backup_worker_state}" == "healthy" ]]; then
      backup_worker_running=true
      break
    fi
    if [[ "${backup_worker_state}" == "exited" || "${backup_worker_state}" == "dead" ]]; then
      break
    fi
    sleep 2
  done

  if [[ "${backup_worker_running}" != "true" ]]; then
    die "Backup worker did not become healthy; inspect it with: docker compose logs backup-worker"
  fi
  backup_worker_stopped=false
fi

trap - EXIT
echo "PostgreSQL credentials synchronized and dependent services restarted."
