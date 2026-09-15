# FR-06C2A — database-vault source and isolated migration contract

Status: source contract only until the isolated rehearsal receipt and protected CI pass. This part does not authorize production PGDATA movement.

## Decision

PostgreSQL `PGDATA`, including `pg_wal`, moves as one database-vault domain. Raw online file copying is forbidden. Production cutover requires a fresh encrypted R2 recovery point, complete drain of database clients, a clean PostgreSQL shutdown, exact offline copy, mapper-backed candidate start, schema/data/health acceptance, and retention of the old PGDATA read-only through the rollback window.

The candidate is a preallocated 16 GiB LUKS2/ext4 vault using the FR-06 cryptographic contract. The database volume mounts `nodev,nosuid,noexec`; PostgreSQL binaries remain in the container image, so executable data files are not required. No persistent production unlock key may live on the unencrypted root.

## Restart and boot boundary

The production Compose stack has 24 database-client service definitions. FR-06C2 adds a database admission overlay that pins those clients plus PostgreSQL itself to `restart: no`. This intentionally extends the FR-06B admission policy to communication/observer/Telegram/reconciler services that also connect to PostgreSQL. Docker or host restart must never make a database client race a locked candidate vault.

The PostgreSQL socket volume remains ephemeral and outside the vault. The existing read-only `/workspace` mount remains unchanged. The only protected storage replacement is `/var/lib/postgresql/data`, mapped to the exact `pgdata` subpath of the mapper-backed volume so ext4 root metadata such as `lost+found` never becomes part of PGDATA.

## Isolated rehearsal requirement

Before any production provisioning, an isolated lab must prove with synthetic data only:

- same PostgreSQL 16 hardened image on source and target;
- source cluster reaches clean `shut down` state before physical copy;
- offline file manifest matches the encrypted target exactly;
- `pg_wal` is included;
- wrong key fails and an independent recovery key reopens the LUKS2 vault;
- target PostgreSQL starts from the copied cluster and returns the expected synthetic row;
- the raw closed LUKS backing file does not expose a synthetic plaintext marker;
- all lab containers, Docker volumes, mappings, keys, mounts and backing files are removed.

The rehearsal is not a production restore and does not prove production downtime, production p95, or owner acceptance.

## Production boundary after protected merge

A later FR-06C2B operational part may provision and cut over only after a fresh client-side-encrypted R2 backup plus independent restore validation, external active/recovery-key and header custody, current capacity, exact service-drain topology and a bounded maintenance window all pass. PostgreSQL must be the first database service to return; credential reconciliation and application clients start only after candidate DB health and integrity acceptance.
