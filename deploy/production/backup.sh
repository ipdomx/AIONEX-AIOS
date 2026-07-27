#!/usr/bin/env bash
set -euo pipefail

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"

docker compose -f deploy/production/docker-compose.production.yml exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-aios}" "${POSTGRES_DB:-aios}" \
  > "$BACKUP_DIR/aios-$STAMP.sql"

tar -czf "$BACKUP_DIR/aios-$STAMP.tar.gz" \
  "$BACKUP_DIR/aios-$STAMP.sql" deploy/production
rm -f "$BACKUP_DIR/aios-$STAMP.sql"

echo "Backup created: $BACKUP_DIR/aios-$STAMP.tar.gz"
