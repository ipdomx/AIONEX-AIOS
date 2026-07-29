# AIONEX AIOS Final Production Release

Production endpoints:

- Web: `https://ai.vip-e.net`
- API: `https://api.ai.vip-e.net`

## Final deployment sequence

1. Copy `.env.production.example` to `.env.production` and replace every
   `CHANGE_ME` value. `AIOS_BOOTSTRAP_OWNER_PASSWORD` is required only while
   creating the first Owner account; clear it after the first successful login
   unless you are performing an intentional reset.
2. Run `bash deploy/production/deploy.sh`. The deployment script runs the
   fail-closed release validation before it pulls, builds, or starts services.
3. Verify the backend and `backup-worker` are healthy, then verify the Owner
   production-runtime and Recovery pages.
4. Queue an Owner backup and restore-validation drill. The worker must record
   both operations as `completed` before the release backup gate can pass.
5. During a controlled maintenance window, test the exact Owner artifact with
   `bash deploy/production/restore.sh --owner-backup-id <uuid>`. The script
   resolves only a completed database record, exports its immutable custom
   archive from the protected volume, verifies its SHA-256 checksum, size, and
   PostgreSQL header, stops the API before draining the worker, rejects queued
   or running recovery jobs, and applies `pg_restore` in one transaction. It
   restarts both services and waits for their healthchecks before reporting
   success.
6. The legacy off-host path remains available: run
   `bash deploy/production/backup.sh`, copy both the resulting archive and its
   adjacent `.sha256` sidecar to protected storage, and test them with
   `bash deploy/production/restore.sh <backup.tar.gz>`.

## PostgreSQL credentials and existing data

PostgreSQL only applies `POSTGRES_PASSWORD` when it initializes an empty data
directory. If credentials change while this stack's `postgres_data` volume
already exists, reconcile the stored role without deleting the volume:

```bash
cd web-dashboard
COMPOSE_FILE=../deploy/production/docker-compose.production.yml \
ENV_FILE=../deploy/production/.env.production \
./scripts/reconcile-postgres-credentials.sh
```

Always pass the Compose and environment files that created the volume. The
stack in this directory and `web-dashboard/docker-compose.production.yml` are
separate Compose projects with separate named volumes; they are not
interchangeable deployment commands. Switching between them can make a
different, empty volume appear even though the original data still exists.
Choose one stack per server and keep using it.

Existing environment files may retain a bundled `DATABASE_URL` alongside
`POSTGRES_*`. The backend, backup worker, and reconciliation script honor that
URL when it uses `postgresql+asyncpg`, targets the Compose service `postgres`,
and contains a complete identity; no manual environment-file rewrite is
required. Its user, password, and database are authoritative for backward
compatibility. Compose runs the authenticated reconciliation gate before the
backend, so a stored password from an existing volume is synchronized
automatically. Valid external URLs skip local reconciliation, malformed values
fail before mutation, and the gate never deletes or recreates `postgres_data`.

Owner backups are custom PostgreSQL archives in the persistent `backup_data`
volume and are referenced by immutable checksum and size in the database.
The worker retains the newest backup per scope, active recovery references, and
the latest validated recovery evidence. It expires older artifacts according
to `BACKUP_RETENTION_COUNT` and `BACKUP_RETENTION_DAYS`, while
`BACKUP_MIN_FREE_BYTES` reserves additional capacity beyond the live database
size before `pg_dump` starts.
Legacy archives and their required `.sha256` sidecars are stored under
`deploy/production/backups/` with restrictive permissions and are excluded from
Git. Copy either backup class to protected off-host storage according to the
operating runbook. The restore script accepts both formats and rejects missing
records, unsafe paths, checksum/size mismatch, queued or running recovery jobs,
or ambiguous legacy archives before it changes the database.
