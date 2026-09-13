# FR-05A1 — Client-side encryption contract

Scope: lock the encryption and key-separation contract before implementation.

Current offsite replication already uses HTTPS, a private R2 bucket, object metadata checks, and full checksum readback. This is not enough for FR-05. Provider-side encryption at rest is not accepted as the FR-05 client-side encryption requirement.

Required before encrypted rollout:
- Encrypt the PostgreSQL dump before upload.
- Encrypt the platform asset snapshot before upload.
- Encrypt the manifest or keep only non-sensitive signed metadata in it.
- Prove wrong-key restore fails closed.
- Prove tampered ciphertext fails closed before extraction or restore.
- Keep decryption material outside Git, reports, logs, DB dumps, asset snapshots, backup object payloads, and image layers.
- Retain decryption material for all unexpired backup generations so rotation does not orphan recoverable backups.

This is a design/contract slice only. It does not change Cloudflare, R2 configuration, backup-worker runtime, or production backup behavior.
