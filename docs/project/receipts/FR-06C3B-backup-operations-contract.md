# FR-06C3B — isolated local-backup and Redis operations rehearsal

Status: source contract and isolated rehearsal only. Production was not mutated.

The local-backup path is intentionally different from Redis. `backup_data` is a local recovery cache whose bytes must migrate exactly, but only after `backup-worker` is stopped and active backup/restore work is zero. The candidate remains a 16 GiB LUKS2/ext4 `local-backup-vault`, with Backend read-only and Backup Worker read-write. The legacy source remains read-only until a new client-side-encrypted R2 backup and independent restore succeed from the candidate.

Redis is not promoted to disaster-recovery authority. The 8 GiB `operations-vault` path must start Redis empty or explicitly reconcile/flush volatile namespaces and rebuild runtime state from PostgreSQL and other durable authorities. Raw copying of the live legacy AOF is not an accepted recovery method. Sanitized non-container operational logs are owned by this domain; Docker JSON logs remain deferred to the later container-runtime vault.

The isolated rehearsal used only synthetic data, disposable file-backed LUKS2 images, tmpfs keys and disposable Docker containers. Backup stable-copy manifests matched; wrong keys were rejected; recovery and active keys reopened the backup vault; the closed image did not expose the synthetic plaintext marker. Redis started empty without copying a legacy AOF, persisted one synthetic volatile key, reopened under the recovery key, then an explicit reconciliation flush returned it to zero keys and the empty state survived an active-key reopen. Every temporary mapping, mount, key, image, source tree and Redis container was removed. Production container identity remained unchanged.

No production vault creation, `backup_data` copy, Redis stop/flush, log movement, service restart, admission change or Cloudflare change is authorized by C3B. C3C is the next protected source boundary.
