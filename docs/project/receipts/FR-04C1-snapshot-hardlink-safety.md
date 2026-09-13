# FR-04C1 — Snapshot hardlink safety policy

Scope: tighten the platform asset companion snapshot safety boundary without adding any backup roots.

Acceptance:
- Symlinks and non-regular files remain rejected.
- Hardlinked files are explicitly rejected with `st_nlink != 1`.
- Existing included production roots were checked before the change and had zero hardlinks, zero symlinks, and zero special files.
- Cache/socket/model volumes remain excluded from platform asset snapshots.
