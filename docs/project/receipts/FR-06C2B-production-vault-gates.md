# FR-06C2B — database-vault provisioning and recovery gates

Status: source-only until protected merge. This part creates no production vault merely by merging and never authorizes PGDATA movement.

FR-06C2B separates **empty-vault provisioning** from the later PostgreSQL cutover. The executor accepts active/recovery key bundles only from the fixed tmpfs key root, binds a fresh encrypted-R2/restore receipt and a bounded owner window into a single-use plan, creates one preallocated 16 GiB LUKS2/ext4 vault, creates only the `pgdata` subdirectory, and registers one mapper-backed external Docker volume. It never stops PostgreSQL, reads or copies production PGDATA, restarts database clients, opens application admission, or changes Cloudflare.

The candidate uses LUKS2 `aes-xts-plain64`/512-bit XTS with Argon2id, ext4 label `AIONEX06_DB`, and mount options `nodev,nosuid,noexec`. The active and recovery keys are independent. Raw key material is never retained in Git, project receipts, the unencrypted root, the R2 header object, or command output.

The LUKS2 header is staged only in `/run/aionex-fr06c2/headers` and copied into backup-worker tmpfs for the dedicated custody helper. That helper uploads a new private R2 object, validates metadata and performs full SHA-256 readback. Recovery-key proof then closes/reopens the **empty** vault and finally reopens it with the active key. This is still pre-cutover; production PostgreSQL remains on legacy PGDATA.

A Docker `ExecStartPre` drop-in is shipped as source but **must not be installed during C2B provisioning**. Installing it before the database cutover would unnecessarily make a currently legacy PostgreSQL deployment depend on an empty candidate vault. Installation belongs only after C2C has successfully moved PostgreSQL to the encrypted domain and retained rollback.

A later C2C part must separately implement and prove database-client drain, clean PostgreSQL shutdown, exact offline manifest copy into `pgdata`, candidate PostgreSQL start, schema/data acceptance, rollback and post-cutover encrypted backup/restore. C2B itself does none of those operations.
