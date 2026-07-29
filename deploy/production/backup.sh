#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env.production}"
COMPOSE_FILE="${COMPOSE_FILE:-${SCRIPT_DIR}/docker-compose.production.yml}"
[[ -f "${ENV_FILE}" ]] || {
  echo "Missing production environment file: ${ENV_FILE}" >&2
  exit 1
}
[[ -f "${COMPOSE_FILE}" ]] || {
  echo "Missing production Compose file: ${COMPOSE_FILE}" >&2
  exit 1
}
ENV_FILE="$(realpath "${ENV_FILE}")"
COMPOSE_FILE="$(realpath "${COMPOSE_FILE}")"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_DIR:-${SCRIPT_DIR}/backups}"
SQL_NAME="aios-${STAMP}.sql"
ARCHIVE_PATH="${BACKUP_DIR}/aios-${STAMP}.tar.gz"
SQL_PATH="${BACKUP_DIR}/${SQL_NAME}"
mkdir -p "${BACKUP_DIR}"
cleanup_plaintext() {
  rm -f "${SQL_PATH}"
}
trap cleanup_plaintext EXIT

AIOS_ENV_FILE="${ENV_FILE}" \
  docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T postgres \
  sh -ceu 'pg_dump --clean --if-exists --no-owner --no-privileges --no-password --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' \
  > "${SQL_PATH}"

tar -czf "${ARCHIVE_PATH}" -C "${BACKUP_DIR}" "${SQL_NAME}"
cleanup_plaintext
trap - EXIT

echo "Backup created: ${ARCHIVE_PATH}"
