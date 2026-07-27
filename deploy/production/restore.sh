#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="${1:-}"
if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "Usage: $0 <backup.tar.gz>" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

tar -xzf "$ARCHIVE" -C "$TMP_DIR"
SQL_FILE="$(find "$TMP_DIR" -name 'aios-*.sql' -type f | head -n1)"
if [[ -z "$SQL_FILE" ]]; then
  echo "Backup SQL file not found." >&2
  exit 1
fi

docker compose -f deploy/production/docker-compose.production.yml exec -T postgres \
  psql -U "${POSTGRES_USER:-aios}" -d "${POSTGRES_DB:-aios}" < "$SQL_FILE"

echo "Restore completed from $ARCHIVE"
