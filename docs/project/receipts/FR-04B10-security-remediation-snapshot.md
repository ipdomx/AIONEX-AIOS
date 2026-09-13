# FR-04B10 — Security remediation snapshot

Scope: add `security_remediation_data` only to platform backup snapshots.

Acceptance:
- `security_remediation_data` is mounted read-only in `backup-worker`.
- `backup-asset-root-init` prepares `/var/lib/aionex/security-remediations` privately as `0700:1000:1000`.
- `docker-entrypoint.sh` accepts the prepared read-only remediation root and fails closed on unsafe ownership or permissions.
- Snapshot manifests include `security_remediation_data` root totals and per-file hashes.
- Symlinks, non-regular files, group/world-readable paths, and path traversal remain rejected.
- `security_tool_cache_data`, `project_npm_cache_data`, and socket/cache volumes are not added in this segment.
