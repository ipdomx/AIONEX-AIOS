# FR-04B6 — mobile release asset snapshot

Scope: add `mobile_release_data` only to platform backup snapshots.

Acceptance:
- `mobile_release_data` is mounted read-only in `backup-worker`.
- `backup-asset-root-init` prepares `/var/lib/aionex/mobile-releases` with private ownership and mode.
- `docker-entrypoint.sh` keeps read-only mobile delivery readers compatible, while backup-enabled workers fail closed on unsafe ownership or permissions.
- Snapshot manifests include mobile_release_data root totals and per-file hashes.
- Symlinks, non-regular files, unsafe permissions, and path traversal remain rejected by the existing asset snapshot executor.
- No realtime, audio ingress, security, cache, or socket roots are added in this segment.
