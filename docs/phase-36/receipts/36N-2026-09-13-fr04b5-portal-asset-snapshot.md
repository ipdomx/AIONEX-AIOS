# Phase 36 receipt — FR-04B5 portal asset snapshot

Scope: add `portal_asset_data` only to the protected platform asset companion snapshot.

Acceptance:
- `portal_asset_data` is mounted read-only in `backup-worker`.
- `backup-asset-root-init` prepares `/var/lib/aionex/portal-assets` with private ownership and mode.
- `docker-entrypoint.sh` accepts a prepared read-only portal root for `backup-worker` and fails closed on unsafe ownership or permissions.
- Snapshot manifests include portal root totals and per-file hashes.
- Symlinks, non-regular files, unsafe permissions, and path traversal remain rejected.
- No realtime, mobile, audio ingress, security roots, or cache roots are added in this segment.
