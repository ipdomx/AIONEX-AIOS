# Phase 36N — Cloudflare R2 off-site DR Production acceptance — 2026-09-08

## Scope

This receipt closes G20, the previously open off-site backup/disaster-recovery gap, using the Owner-provisioned private Cloudflare R2 Standard bucket `aionex-production-backups`. AWS/Bedrock/XR/payment-provider work remains deferred by Owner instruction and is not part of this acceptance.

## Protected source chain

- PR #592 implemented durable R2 replication/restore evidence and merged as `6e5f30dca3597cd5ae7fdecf448cb58365f58a3a` after the protected matrix passed.
- PR #593 moved the intended service secret mount outside the workspace and merged as `e0dbe8261ff850d05b6557eaf3ff91692f1e1dad` after the protected matrix passed.
- Production acceptance correctly rejected a group-readable credential because `OffsiteBackupReplicator` requires no group/other credential permissions. The Backup Worker was immediately rolled back to the previously accepted ignored runtime path and returned healthy/restart=0.
- PR #594 fixed the design by keeping the canonical host credential `root:root` mode `0400`, mounting that source read-only, and copying it inside the root entrypoint to `/run/aionex/r2-backup.env` as `aionex:aionex` mode `0400` before privilege drop. All required Backend, Production Docker, CodeQL, SBOM, dependency, browser, frontend, hygiene, reporting and Docker-upstream gates passed; it merged as `847dacd7129174e7dcc8e4c528e5862a17371b75`.

## Secret and runtime acceptance

- Canonical credential: `/root/.config/aionex/r2-backup/credentials.env`, `root:root`, mode `0400`; no credential value is stored in Git or this receipt.
- Backup Worker source mount is read-only at `/run/operator-secrets/r2-backup-source.env`.
- Entrypoint runtime copy is `/run/aionex/r2-backup.env`, UID/GID 1000, mode `0400`.
- The live Backup Worker process runs as UID/GID 1000, can read the runtime credential and cannot write it.
- Both transitional host copies were removed: `/opt/AIOS/.runtime-secrets/r2-backup.env` and `/etc/aionex/r2-backup/credentials.env` are absent.
- A cold Backup Worker recreate after deleting those transitional copies returned `running/healthy`, restart count `0`, and the live Backup Worker preflight passed.
- The rotation installer now writes only the canonical root-owned `0400` credential source.

## Real off-site backup and restore drill

A fresh Production platform backup was queued only after the final merged secret-bootstrap runtime was healthy:

- Backup ID: `1b9a0849-8163-4211-b6f2-f8dd0832c4ee`
- Status: `completed`
- Database size: `20,670,294` bytes
- Database SHA-256: `ff9fdf27b9d40088ac1e801546d73bc6e6156e6c3c6c490753ef9404db05885c`
- Off-site status: `completed`
- Durable off-site evidence: present
- Off-site completion timestamp: present

The matching R2 prefix contains exactly three required objects: `database.dump`, `manifest.json`, and `three-d.tar`, totaling `20,681,065` bytes. Authenticated R2 preflight passed.

A restore validation was then executed against that exact backup:

- DR run ID: `6fe89481-13e6-4cf4-b1d6-ddb7d72a78ce`
- Operation: `restore_validation`
- Status: `completed`
- `validated=true`
- `offsite_required=true`
- `offsite_validated=true`
- `three_d_snapshot_required=true`
- `three_d_snapshot_validated=true`
- Restored database checksum/size evidence matches the selected backup.

The validation path downloads the R2 copy, verifies remote evidence/checksums, restores PostgreSQL into the isolated worker-managed scratch database, verifies restored user tables, validates the required 3D companion archive, and cleans the validation artifacts/scratch database.

## Failure/recovery operations

When off-site mode is enabled, a local backup can remain completed while R2 replication is durably marked failed. The Backup Worker emits a critical Owner notification through In-app + Telegram for an off-site failure and emits a recovery notification only after a later backup passes full remote checksum readback. Release/security/operations backup gates fail closed when the required R2 evidence/remote restore evidence is missing.

## Final Production state

- Production containers: `35/35` running.
- Unhealthy containers: `0`.
- Total current container restart count: `0`.
- `/ready=200`.
- Active Backup jobs: `0`; active DR jobs: `0`.
- Capacity Guard timer: enabled + active; last watcher result success/0; CPU, RAM, disk, normalized load, network and swap are all at healthy levels.
- Owner finalization with the Redis lifecycle initialized: `completion=100`; all ten health/release checks are `passed`; Phase 36 current batch remains `COMPLETE`.

## Immutable release anchor

Release manifest `docs/phase-36/release-manifests/AIOS-2026-09-08-R2-DR-847dacd.json` binds source commit `847dacd7129174e7dcc8e4c528e5862a17371b75`, Alembic head `20260907_0045`, both Production Compose definitions and all 35 live container image IDs. Manifest SHA-256: `4a08e8814376ff03818c5de8f77a5b6aa80edb42c86b0ddeae2af1c51453f394`.

## Result

**G20 OFF-SITE BACKUP / DR = CLOSED.** The system now has a real private off-host R2 copy, durable replication evidence, full remote checksum readback, bounded retention, remote restore validation, required 3D recovery validation, fail-closed release gates, and Owner failure/recovery alerts. This does not claim multi-host application HA or host-level disk encryption; those are separate infrastructure authority boundaries.
