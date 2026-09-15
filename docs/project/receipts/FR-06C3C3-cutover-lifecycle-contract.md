# FR-06C3C3 — guarded local-backup and Redis cutover lifecycle contract

Status: design contract only; no production execution.

The two C3 data paths have deliberately different semantics. `backup_data` is copied exactly, offline, only after Backup Worker stops and active backup/restore work is zero. Backend and Backup Worker are then recreated against the encrypted local-backup vault with their existing read-only/read-write split, and C3D cannot close until a new encrypted R2 backup plus independent restore succeeds from that candidate.

Redis is not copied. The rendered production topology currently contains 26 Redis-dependent service definitions, including Backend, workers, realtime-egress and LiveKit. The production executor must resolve the exact running instances and project-worker scale at execution time, stop those clients before Redis, and start the encrypted candidate empty. `DBSIZE=0` is required before any client restart. Only the previously running clients may return, under guarded restart policy. Runtime caches, locks and queue hints rebuild from PostgreSQL and other durable authorities.

Rollback never copies a candidate AOF into the legacy Redis volume. The old AOF is diagnostic evidence, not disaster-recovery authority; any fallback follows an explicit empty/reconciled Redis path. This avoids resurrecting stale leases, queue hints or locks.
