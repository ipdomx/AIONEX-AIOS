# FR-04C1 — Hard-link rejection for asset backups

Scope: reject hard-linked files inside protected platform asset roots before archive creation.

Acceptance:
- Every regular source file must have `st_nlink == 1`.
- Hard-linked files fail closed with `BackupExecutionError` before entering the backup archive.
- Existing symlink, non-regular file, permission, and path traversal protections remain unchanged.
- No backup scope expansion, service wiring, cache/socket policy, or runtime deployment occurs in this source segment.
