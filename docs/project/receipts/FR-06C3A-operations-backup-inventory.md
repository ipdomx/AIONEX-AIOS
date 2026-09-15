# FR-06C3A — local backup and operations inventory

Status: live read-only inventory complete; no FR-06C3 production mutation is authorized by this part.

## Local backup domain

`web-dashboard_backup_data` is the local recovery cache. The Backend mounts it read-only and `backup-worker` mounts it read-write at `/var/lib/aionex/backups`. The live volume currently contains 67 regular files and about 688.8 MB, with no symlinks observed. C3 keeps the C1 16 GiB `local-backup-vault` plan.

The production migration must not copy while `backup-worker` can write. It must first prove zero active backup/restore work, stop the writer, seal the legacy source, make an exact offline manifest copy, switch only the Backend/Backup Worker mounts, retain the legacy source read-only, and prove a fresh client-side-encrypted R2 backup plus independent restore from the candidate before closure.

## Redis and operations domain

Redis remains AOF-enabled on `web-dashboard_redis_data`, with `appendfsync=everysec` and `maxmemory-policy=noeviction`. The current volume is about 16.3 MB and Redis reports two keys. Redis is operational state, not a disaster-recovery authority: FR-04C3 already established that restored environments must start Redis empty or flush/reconcile runtime namespaces and rebuild from durable authorities.

Therefore C3 will not treat a raw live AOF copy as authoritative recovery. The selected path is an encrypted `operations-vault` plus an explicit empty/reconciliation rehearsal. Any retained sanitized non-container logs must move under that domain or become volatile. Docker JSON logs remain owned by the later `container-runtime-vault`, not by C3.

## Safety boundary

C3A performs no vault provisioning, service stop, Redis flush, file copy, log movement, admission change or Cloudflare change. The next part is an isolated rehearsal only: local-backup exact copy/recovery plus Redis empty/rebuild behavior, before any protected production source or runtime cutover.
