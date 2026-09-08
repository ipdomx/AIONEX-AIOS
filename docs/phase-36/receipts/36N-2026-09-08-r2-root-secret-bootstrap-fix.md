# Phase 36N — R2 root-only secret bootstrap fix — 2026-09-08

A post-merge Production acceptance of PR #593 correctly failed closed because the R2 credential parser rejects group-readable credential files. Production was immediately rolled back to the previously accepted ignored runtime credential path and the Backup Worker returned healthy with restart count reset to zero.

This candidate removes the need for a group-readable service credential. The canonical host credential remains root:root mode 0400 outside the repository. Production Compose bind-mounts that root-only source read-only at `/run/operator-secrets/r2-backup-source.env`; the root entrypoint copies it before privilege drop to `/run/aionex/r2-backup.env` as aionex:aionex mode 0400, then exports the runtime path. The Backup Worker continues as UID/GID 1000 and cannot write the runtime credential.

Pre-CI acceptance: both Production Compose variants validate; shell syntax validates; an isolated entrypoint probe produced UID/GID 1000 with runtime credential mode 0400 and write denied; authenticated R2 preflight through the candidate entrypoint passed; focused backup/off-site/3D/database regression passed 71 tests with 1 skip. No credential value is committed or printed.

This receipt remains a candidate until protected CI passes, the change is merged, Production recreates the Backup Worker from the merged source, the ignored workspace credential is removed, and a new R2-backed Production backup plus remote restore validation both succeed.
