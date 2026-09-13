# FR-04B9 — Security source asset snapshot

Scope: add `security_source_data` only to platform backup snapshots.

Acceptance:
- `security_source_data` is mounted read-only in `backup-worker`.
- `backup-asset-root-init` prepares `/var/lib/aionex/security-sources` privately as `0700:1000:1000`.
- Snapshot manifests include `security_source_data` root totals and per-file hashes.
- Symlinks, non-regular files, group/world-readable paths, and path traversal remain rejected.
- `security_remediation_data`, security tool cache, project npm cache, and socket volumes are not added in this segment.
