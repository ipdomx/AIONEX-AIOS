# FR-04B3 — Media asset backup snapshot

Scope: add `media_asset_data` only to the protected platform asset companion snapshot.

Acceptance:
- `media_asset_data` is mounted read-only in `backup-worker`.
- `backup-asset-root-init` prepares `/var/lib/aionex/media-assets` with private ownership and mode.
- `docker-entrypoint.sh` accepts a prepared read-only media root for `backup-worker` and fails closed on unsafe ownership or permissions.
- Snapshot manifests include media root totals and per-file hashes.
- Symlinks, non-regular files, unsafe permissions, and path traversal remain rejected by the existing asset snapshot executor.
- No `studio_asset_data`, `portal_asset_data`, or `project_npm_cache_data` is added in this segment.

Runtime deployment is recorded separately after protected merge.
