# FR-06C3C1 — mapper-backed local-backup and operations overlays

Status: source-only overlays and render validator. No production mutation.

The candidate replaces only three protected mounts: Backend's read-only `/var/lib/aionex/backups`, Backup Worker's read-write `/var/lib/aionex/backups`, and Redis `/data`. Backup mounts resolve to the external mapper-backed `aionex-fr06-local-backup-vault` `backups` subpath; Redis resolves to `aionex-fr06-operations-vault` `redis`. Legacy volume declarations remain in the base Compose solely as rollback source definitions, but no candidate service may mount them.

Redis changes to `restart:no` so Docker cannot restore it automatically before operations-vault admission/reconciliation is revalidated. Backend and Backup Worker already inherit `restart:no` from the accepted FR-06B guarded admission overlay. C3C1 does not create either external volume, mapper, key or vault and has no lifecycle executor.

The validator renders all Compose profiles against both the accepted and candidate stacks, requires exact target/subpath/read-write semantics, rejects any remaining legacy protected mount, requires exact external volume names, and rejects unrelated service or top-level drift.
