# FR-06C3C4 — guarded local-backup cutover executor

Status: source-only executor. It is not a production authorization.

The executor is intentionally scoped to `backup_data`. It captures the exact running Backend and Backup Worker topology, binds it and fresh encrypted backup/restore evidence to a single-use expiring plan, and stops Backup Worker before Backend. Once no legacy volume consumer remains it seals the legacy source read-only, performs an offline stable copy with exact safe manifests, and recreates only the two prior services against the encrypted local-backup vault. The existing read-only Backend / read-write Backup Worker split is validated after start.

Any failure before candidate start restores the retained legacy source directly. Any failure after candidate start first stops the candidate writer and Backend, then performs a stable reverse delta before restoring the legacy topology. Explicit rollback uses the same no-live-copy rule and retains the candidate for evidence.

Redis, operational logs, keys, vault provisioning, admission and Cloudflare are outside this executor. C3D cannot close merely because the cutover succeeds: a fresh client-side-encrypted R2 backup and independent restore validation must then pass from the candidate while legacy `backup_data` remains read-only.
