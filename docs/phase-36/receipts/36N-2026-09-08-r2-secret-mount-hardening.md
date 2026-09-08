# Phase 36N — R2 service-secret mount hardening — 2026-09-08

This candidate removes the Cloudflare R2 Backup Worker credential dependency on the ignored repository workspace runtime copy. No credential value is committed or recorded in this receipt.

The canonical credential remains outside the repository at `/root/.config/aionex/r2-backup/credentials.env` with root:root mode 0400. A service-readable copy is maintained outside the repository at `/etc/aionex/r2-backup/credentials.env` with numeric ownership 0:1000 and mode 0440, under a 0750 directory. The Backup Worker receives only that file as a read-only bind mount at `/run/operator-secrets/r2-backup.env`; its effective process continues to run as UID/GID 1000 rather than root.

Candidate acceptance before merge:
- Both Production Compose variants parse successfully when supplied the real Production environment path.
- A disposable container running as UID/GID 1000 can read the mounted service secret and cannot write it.
- Exactly the four expected `R2_BACKUP_*` keys are present; values are not printed.
- The host-side credential installer was updated so future credential rotation atomically refreshes both the canonical root-only file and the service-readable copy without writing into `/opt/AIOS`.

The existing R2 implementation already emits durable Owner notifications on verified off-site failure and a recovery notification after a subsequent fully verified replication. Production activation of this hardening is deferred until protected CI passes and the change is merged.
