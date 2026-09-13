# FR-04C3 — Redis recovery and rebuild contract

Scope: document and test the Redis disaster-recovery contract without adding `redis_data` to the protected asset snapshot.

Policy:
- `redis_data` remains excluded from platform asset snapshots and off-host DR artifacts.
- Redis keeps production restart durability via AOF and `noeviction`, but it is not the cross-environment recovery authority.
- After a restored environment is built, Redis must start empty or have runtime namespaces flushed before traffic opens.
- Durable authority remains PostgreSQL logical backup plus the protected platform asset snapshot.
- Old Redis state must not resurrect stale project leases, passkey/social registration challenges, throttles, circuit state, or idempotency guards after a DB/assets restore.
- `project_npm_cache_data`, `security_tool_cache_data`, `ollama_model_data`, and `postgres_socket` remain explicitly outside asset snapshots.

Acceptance:
- The machine-readable JSON contract names `redis_data` as excluded and states the post-restore empty/flush action.
- Compose keeps Redis AOF/noeviction and `redis_data:/data` for same-host runtime restarts.
- `backup-worker` and `backup-asset-root-init` do not mount `redis_data` as an asset source.
- `three_d_asset_backup.py` does not include `redis_data` as a `_SourceRoot`.
