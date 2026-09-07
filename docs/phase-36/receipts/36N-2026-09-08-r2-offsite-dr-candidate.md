# Phase 36N — Cloudflare R2 off-site DR candidate — 2026-09-08

Owner provisioned a private Cloudflare R2 Standard bucket dedicated to AIONEX Production backups and a bucket-scoped Object Read & Write Account API token. No credential value is committed or recorded in this receipt.

Pre-source acceptance from the Production host proved the supplied authority end to end: bucket preflight, object PUT, full GET checksum readback, LIST, DELETE and post-delete absence all passed. The private credential file is root-owned mode 0400, lives outside Git, and a second ignored runtime copy is available read-only to the Backup Worker through the existing `/workspace` mount.

The protected candidate adds durable off-site evidence to `BackupRecord`, full database + required 3D companion replication to R2, SHA-256 full remote readback verification, a manifest per backup, bounded R2 retention, remote download + real PostgreSQL restore validation, remote 3D snapshot validation, Owner failure/recovery notification rows, and fail-closed release/security/operations gates whenever off-site replication is enabled.

Focused backup/DR regression: 55 passed, 1 skipped. Ruff on changed Python files: PASS. Mypy on changed source files: PASS. Fresh PostgreSQL 16 migration from base through `20260907_0045`: PASS with all three off-site evidence columns present.

This receipt is a candidate only until protected CI merges the source, Production migrates to `20260907_0045`, `BACKUP_OFFSITE_ENABLED=true` is armed, and a new Production backup is uploaded to R2 then restored from the R2 copy successfully. No off-site completion claim is made before that acceptance.
