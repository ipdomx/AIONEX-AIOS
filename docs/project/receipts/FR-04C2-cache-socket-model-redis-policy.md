# FR-04C2 — Cache/socket/model exclusions and Redis policy

Scope: lock the FR-04 recovery boundary after FR-04B completed asset-root coverage.

Authoritative backup inputs:
- PostgreSQL remains logically backed up through the database dump path.
- Platform asset snapshot roots are the explicitly enabled FR-04B roots only.

Explicit exclusions from platform asset snapshots:
- `project_npm_cache_data` — rebuildable npm/browser automation cache.
- `security_tool_cache_data` — rebuildable security tooling/home cache.
- `ollama_model_data` — large rebuildable model cache; restored through provider/model provisioning, not asset archive.
- `postgres_socket` — ephemeral runtime socket volume.
- `backup_data` — backup destination, never recursively included in its own payload.
- `redis_data` — operational Redis AOF state; FR-04C keeps it outside the asset snapshot and requires a separate consistency/rebuild contract instead of silent omission.

Policy:
- These excluded roots must not be mounted into `backup-worker` as asset sources.
- These excluded roots must not appear in `ThreeDAssetSnapshotExecutor` source root IDs.
- Redis must remain an explicit FR-04C decision item until the recovery contract is closed.
