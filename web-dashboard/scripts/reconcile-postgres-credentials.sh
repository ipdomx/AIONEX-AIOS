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
  if [[ "${credentials_changed}" == "true" ]]; then
    compose up -d --no-deps --force-recreate backend >/dev/null
  fi
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

compose_services="$(compose config --services)"
for required_service in postgres postgres-credential-reconciler backend; do
  grep -qx "${required_service}" <<<"${compose_services}" ||
    die "the ${required_service} service is missing from the Compose project"
done
has_backup_worker=false
if grep -qx "backup-worker" <<<"${compose_services}"; then
  has_backup_worker=true
fi

echo "Starting PostgreSQL..."
compose up -d --no-deps postgres

ready=false
for ((attempt = 1; attempt <= 30; attempt++)); do
  if compose exec -T postgres sh -ceu \
    'pg_isready --host 127.0.0.1 --port 5432 --quiet'
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

echo "Reconciling and verifying the configured PostgreSQL credentials..."
set +e
compose run --rm --no-deps postgres-credential-reconciler
reconcile_status=$?
set -e
if ((reconcile_status != 0)); then
  # Exit 1 is reserved for a fail-closed configuration or active-job refusal
  # before mutation. Other failures are conservatively treated as possibly
  # post-commit, so cleanup recreates dependent services with the current env.
  if ((reconcile_status != 1)); then
    credentials_changed=true
  fi
  exit "${reconcile_status}"
fi
credentials_changed=true

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
    if [[ "${backup_worker_state}" == "exited" ||
      "${backup_worker_state}" == "dead" ]]; then
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
echo "PostgreSQL credential gate completed and dependent services restarted."
