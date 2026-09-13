# FR-05A2 — Crypto/keyring/envelope contract

FR-05 keeps the existing BackupRecord/R2/readback/retention/restore-validation pipeline and adds client-side authenticated encryption to it. Restic is not selected for FR-05 because replacing the existing pipeline would duplicate or bypass its current evidence and restore contracts.

Locked design:
- AES-256-GCM per R2 object using the `cryptography` streaming Cipher API.
- 32-byte keys, random 12-byte nonce per object, 16-byte GCM tag.
- Database dump, platform asset snapshot, and manifest are encrypted before upload.
- AEAD associated data binds backup ID, object role, R2 object key, envelope/algorithm/key ID, and the already-known plaintext SHA-256/size.
- New encrypted object names use `.aex1`; the manifest is encrypted too.
- The encryption keyring is a separate operator-owned root-only file, not the R2 credential file, not Git, not an image layer, and never uploaded into the backup prefix.
- Rotation creates a new active key and retains old keys as decrypt-only until no retained backup references them. Rotation does not silently orphan or automatically rewrite old backups.
- A recovery copy of the keyring is required outside this server and outside the R2 repository, but its key material must never appear in project reports.
- FR-05 protects offsite objects before upload. It does not claim local `backup_data`, database-volume, or full-disk encryption; those remain FR-06 scope.

This slice is contract-only. No Cloudflare, R2 bucket, backup-worker, or production backup behavior changes here.
