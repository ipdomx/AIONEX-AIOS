#!/usr/bin/env bash
set -euo pipefail

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

ARCHIVE=""
EXPECTED_CHECKSUM=""
EXPECTED_SIZE=""
OWNER_BACKUP_ID=""
OWNER_BACKUP_KIND_HEX=""
OWNER_BACKUP_SCOPE_HEX=""
OWNER_BACKUP_COMPLETED_EPOCH=""
if [[ "${1:-}" == "--owner-backup-id" ]]; then
  OWNER_BACKUP_ID="${2:-}"
  [[ "${OWNER_BACKUP_ID}" =~ ^[[:xdigit:]]{8}-[[:xdigit:]]{4}-[1-5][[:xdigit:]]{3}-[89abAB][[:xdigit:]]{3}-[[:xdigit:]]{12}$ ]] || {
    echo "Owner backup id must be a valid UUID." >&2
    exit 1
  }
elif [[ -n "${1:-}" && -f "${1:-}" ]]; then
  ARCHIVE="$(realpath "${1}")"
  EXPECTED_CHECKSUM="${2:-}"
else
  echo "Usage: $0 --owner-backup-id <uuid> | <backup.dump> <sha256> | <legacy-backup.tar.gz>" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
TMP_DIR="$(realpath "$TMP_DIR")"
backend_stopped=false
backup_worker_stopped=false

compose() {
  AIOS_ENV_FILE="${ENV_FILE}" \
    docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

cleanup() {
  exit_code=$?
  set +e
  if [[ "${backend_stopped}" == "true" ]]; then
    compose up -d backend >/dev/null
  fi
  if [[ "${backup_worker_stopped}" == "true" ]]; then
    compose start backup-worker >/dev/null
  fi
  rm -rf "${TMP_DIR}"
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
      'SELECT count(*) FROM %s WHERE status IN (%L, %L)',
      relation,
      'pending',
      'running'
    ) INTO relation_count;
    total := total + relation_count;
  END IF;

  relation := to_regclass('disaster_recovery_runs');
  IF relation IS NOT NULL THEN
    EXECUTE format(
      'SELECT count(*) FROM %s WHERE status IN (%L, %L)',
      relation,
      'pending',
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

if [[ -n "${OWNER_BACKUP_ID}" ]]; then
  owner_record="$(
    printf '%s\n' \
      "SELECT encode(convert_to(kind, 'UTF8'), 'hex') || chr(9)
              || encode(convert_to(scope, 'UTF8'), 'hex') || chr(9)
              || location || chr(9)
              || checksum || chr(9)
              || size_bytes::text || chr(9)
              || extract(epoch FROM completed_at)::text
       FROM backup_records
       WHERE id = :'backup_id'
         AND status = 'completed'
         AND location IS NOT NULL
         AND checksum IS NOT NULL
         AND size_bytes > 0
         AND completed_at IS NOT NULL;" |
      compose exec -T \
        -e "AIOS_BACKUP_ID=${OWNER_BACKUP_ID}" \
        postgres \
        sh -ceu '
          psql \
            --no-psqlrc \
            --no-password \
            --username "$POSTGRES_USER" \
            --dbname "$POSTGRES_DB" \
            --set ON_ERROR_STOP=1 \
            --set "backup_id=$AIOS_BACKUP_ID" \
            --tuples-only \
            --no-align \
            --quiet
        '
  )"
  [[ -n "${owner_record}" ]] || {
    echo "Completed Owner backup artifact was not found." >&2
    exit 1
  }
  IFS=$'\t' read -r \
    OWNER_BACKUP_KIND_HEX \
    OWNER_BACKUP_SCOPE_HEX \
    owner_location \
    EXPECTED_CHECKSUM \
    EXPECTED_SIZE \
    OWNER_BACKUP_COMPLETED_EPOCH <<<"${owner_record}"
  [[ "${OWNER_BACKUP_KIND_HEX}" =~ ^[[:xdigit:]]+$ &&
    $((${#OWNER_BACKUP_KIND_HEX} % 2)) -eq 0 ]] || {
    echo "Owner backup record has an invalid kind." >&2
    exit 1
  }
  [[ "${OWNER_BACKUP_SCOPE_HEX}" =~ ^[[:xdigit:]]+$ &&
    $((${#OWNER_BACKUP_SCOPE_HEX} % 2)) -eq 0 ]] || {
    echo "Owner backup record has an invalid scope." >&2
    exit 1
  }
  [[ "${owner_location}" =~ ^/var/lib/aionex/backups/backup-[[:xdigit:]]{24}(-[[:xdigit:]]{32})?\.dump$ ]] || {
    echo "Owner backup record points outside the protected backup volume." >&2
    exit 1
  }
  [[ "${EXPECTED_CHECKSUM}" =~ ^[[:xdigit:]]{64}$ ]] || {
    echo "Owner backup record has an invalid checksum." >&2
    exit 1
  }
  [[ "${EXPECTED_SIZE}" =~ ^[1-9][[:digit:]]*$ ]] || {
    echo "Owner backup record has an invalid artifact size." >&2
    exit 1
  }
  [[ "${OWNER_BACKUP_COMPLETED_EPOCH}" =~ ^[[:digit:]]+(\.[[:digit:]]+)?$ ]] || {
    echo "Owner backup record has an invalid completion timestamp." >&2
    exit 1
  }
  [[ -n "$(compose ps -a -q backup-worker)" ]] || {
    echo "Backup worker container is required to export an Owner backup." >&2
    exit 1
  }
  ARCHIVE="${TMP_DIR}/owner-backup.dump"
  compose cp "backup-worker:${owner_location}" "${ARCHIVE}" >/dev/null
  ARCHIVE="$(realpath -e "${ARCHIVE}")"
  [[ "${ARCHIVE}" == "${TMP_DIR}/"* && -f "${ARCHIVE}" && ! -L "${ARCHIVE}" ]] || {
    echo "Exported Owner backup is not a safe regular file." >&2
    exit 1
  }
fi

restore_kind="legacy-sql"
SQL_FILE=""
if [[ "${ARCHIVE}" == *.dump ]]; then
  restore_kind="custom"
  [[ "$(head -c 5 "${ARCHIVE}")" == "PGDMP" ]] || {
    echo "Custom backup is not a PostgreSQL archive." >&2
    exit 1
  }
  [[ "${EXPECTED_CHECKSUM}" =~ ^[[:xdigit:]]{64}$ ]] || {
    echo "A 64-character SHA-256 checksum is required for custom backups." >&2
    exit 1
  }
  actual_checksum="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
  if [[ "${actual_checksum,,}" != "${EXPECTED_CHECKSUM,,}" ]]; then
    echo "Custom backup checksum verification failed." >&2
    exit 1
  fi
  if [[ -n "${EXPECTED_SIZE}" && "$(stat -c %s "${ARCHIVE}")" != "${EXPECTED_SIZE}" ]]; then
    echo "Custom backup size verification failed." >&2
    exit 1
  fi
else
  checksum_file="${ARCHIVE}.sha256"
  [[ -f "${checksum_file}" && ! -L "${checksum_file}" ]] || {
    echo "Legacy backup SHA-256 sidecar is missing or unsafe." >&2
    exit 1
  }
  EXPECTED_CHECKSUM="$(<"${checksum_file}")"
  [[ "${EXPECTED_CHECKSUM}" =~ ^[[:xdigit:]]{64}$ ]] || {
    echo "Legacy backup SHA-256 sidecar is invalid." >&2
    exit 1
  }
  actual_checksum="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
  if [[ "${actual_checksum,,}" != "${EXPECTED_CHECKSUM,,}" ]]; then
    echo "Legacy backup checksum verification failed." >&2
    exit 1
  fi
  archive_entries="$(tar -tzf "$ARCHIVE")"
  if grep -Eq '(^/|(^|/)\.\.(/|$))' <<<"${archive_entries}"; then
    echo "Backup archive contains an unsafe path." >&2
    exit 1
  fi
  sql_count="$(
    grep -Ec '(^|/)aios-[^/]+\.sql$' <<<"${archive_entries}" || true
  )"
  if [[ "${sql_count}" != "1" ]]; then
    echo "Backup archive must contain exactly one aios-*.sql file." >&2
    exit 1
  fi
  sql_entry="$(
    grep -E '(^|/)aios-[^/]+\.sql$' <<<"${archive_entries}" |
      head -n1
  )"
  tar -xzf "$ARCHIVE" -C "$TMP_DIR" -- "$sql_entry"
  SQL_FILE="$(realpath -e "${TMP_DIR}/${sql_entry}")"
  if [[ "${SQL_FILE}" != "${TMP_DIR}/"* || ! -f "${SQL_FILE}" || -L "${SQL_FILE}" ]]; then
    echo "Backup SQL file is not a safe regular file." >&2
    exit 1
  fi
fi

if [[ -n "$(compose ps --status running -q backend)" ]]; then
  backend_stopped=true
  compose stop backend
fi
if [[ -n "$(compose ps --status running -q backup-worker)" ]]; then
  backup_worker_stopped=true
  compose stop backup-worker
fi
running_job_count="$(
  running_recovery_job_count |
    tr -d '[:space:]'
)"
[[ "${running_job_count}" =~ ^[[:digit:]]+$ ]] || {
  echo "Could not verify active backup and restore jobs." >&2
  exit 1
}
if ((running_job_count > 0)); then
  echo "Restore refused because a backup or restore job remains queued or running." >&2
  exit 1
fi

if [[ "${restore_kind}" == "custom" ]]; then
  compose exec -T postgres \
    sh -ceu 'pg_restore --no-password --clean --if-exists --no-owner --no-privileges --exit-on-error --single-transaction --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' \
    < "$ARCHIVE"
else
  compose exec -T postgres \
    sh -ceu 'psql --no-password --set ON_ERROR_STOP=1 --single-transaction --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' \
    < "$SQL_FILE"
fi

if [[ -n "${OWNER_BACKUP_ID}" ]]; then
  compose exec -T \
    -e "AIOS_BACKUP_REPAIR=1" \
    -e "AIOS_BACKUP_ID=${OWNER_BACKUP_ID}" \
    -e "AIOS_BACKUP_KIND_HEX=${OWNER_BACKUP_KIND_HEX}" \
    -e "AIOS_BACKUP_SCOPE_HEX=${OWNER_BACKUP_SCOPE_HEX}" \
    -e "AIOS_BACKUP_LOCATION=${owner_location}" \
    -e "AIOS_BACKUP_CHECKSUM=${EXPECTED_CHECKSUM}" \
    -e "AIOS_BACKUP_SIZE=${EXPECTED_SIZE}" \
    -e "AIOS_BACKUP_COMPLETED_EPOCH=${OWNER_BACKUP_COMPLETED_EPOCH}" \
    postgres \
    sh -ceu '
      psql \
        --no-psqlrc \
        --no-password \
        --username "$POSTGRES_USER" \
        --dbname "$POSTGRES_DB" \
        --set ON_ERROR_STOP=1 \
        --set "backup_id=$AIOS_BACKUP_ID" \
        --set "backup_kind_hex=$AIOS_BACKUP_KIND_HEX" \
        --set "backup_scope_hex=$AIOS_BACKUP_SCOPE_HEX" \
        --set "backup_location=$AIOS_BACKUP_LOCATION" \
        --set "backup_checksum=$AIOS_BACKUP_CHECKSUM" \
        --set "backup_size=$AIOS_BACKUP_SIZE" \
        --set "backup_completed_epoch=$AIOS_BACKUP_COMPLETED_EPOCH"
    ' <<'SQL'
INSERT INTO backup_records (
  id,
  kind,
  scope,
  status,
  location,
  checksum,
  size_bytes,
  lease_token,
  completed_at,
  created_at,
  updated_at
)
VALUES (
  :'backup_id',
  convert_from(decode(:'backup_kind_hex', 'hex'), 'UTF8'),
  convert_from(decode(:'backup_scope_hex', 'hex'), 'UTF8'),
  'completed',
  :'backup_location',
  :'backup_checksum',
  :'backup_size'::bigint,
  NULL,
  to_timestamp(:'backup_completed_epoch'::double precision),
  to_timestamp(:'backup_completed_epoch'::double precision),
  CURRENT_TIMESTAMP
)
ON CONFLICT (id) DO UPDATE
SET kind = EXCLUDED.kind,
    scope = EXCLUDED.scope,
    status = EXCLUDED.status,
    location = EXCLUDED.location,
    checksum = EXCLUDED.checksum,
    size_bytes = EXCLUDED.size_bytes,
    lease_token = NULL,
    completed_at = EXCLUDED.completed_at,
    updated_at = CURRENT_TIMESTAMP;

SELECT 1 / CASE
  WHEN EXISTS (
    SELECT 1
    FROM backup_records
    WHERE id = :'backup_id'
      AND status = 'completed'
      AND location = :'backup_location'
      AND checksum = :'backup_checksum'
      AND size_bytes = :'backup_size'::bigint
      AND lease_token IS NULL
      AND completed_at IS NOT NULL
  )
  THEN 1
  ELSE 0
END;
SQL
fi

if [[ "${backend_stopped}" == "true" || "${backup_worker_stopped}" == "true" ]]; then
  compose up -d --wait --wait-timeout 180 backend backup-worker
  backend_stopped=false
  backup_worker_stopped=false
fi

echo "Restore completed from $ARCHIVE"
