# FR-06C1 — live host-data inventory and protected sequencing

Status: live read-only inventory complete; no FR-06C production data movement is authorized by this part.

## Scope

FR-06B is complete for the eleven authoritative asset/project roots. FR-06C now owns the five remaining encrypted data domains defined by ADR-001 plus encrypted swap and temporary-data controls:

1. **database-vault** — PostgreSQL `PGDATA` including `pg_wal`.
2. **operations-vault** — Redis operational persistence plus retained sanitized non-container operational logs.
3. **local-backup-vault** — the local `backup_data` artifacts used by Backend and Backup Worker.
4. **container-runtime-vault** — Docker/containerd runtime metadata, writable layers and Docker JSON logs after authoritative named volumes are externalized.
5. **host-state-vault** — application/provider/operator secret material and retained audit/release state, excluding only the minimal reviewed management bootstrap required to regain the out-of-band MCP control channel before vault unlock.

Swap must use a fresh random key on every boot. Sensitive temporary data must use `/run`, `/dev/shm`, or a reviewed encrypted path; plaintext `/tmp` and `/var/tmp` may retain only classified non-sensitive rebuildable material.

## Live findings retained by C1

The production root remains plain ext4 on `/dev/md0p2`. PostgreSQL is still in `web-dashboard_postgres_data`; `pg_wal` is inside the same PGDATA. Redis uses AOF in `web-dashboard_redis_data`. Local backup artifacts remain in `web-dashboard_backup_data`. The application secret root and operator state remain on the unencrypted root, and the 8 GiB swap file is plaintext.

A material correction to the FR-06A inventory is now retained: Docker 29 uses the containerd image store. `/var/lib/docker` itself is only about 14.6 GB, while `/var/lib/containerd` is about 398.6 GB, dominated by historical content and overlay snapshots. Blindly duplicating that runtime into a new LUKS file would violate the rollback/free-space safety boundary because the host had only about 322 GB free at C1 inventory time.

The accepted path is therefore **clean runtime reconstruction**, not historical runtime copying. Current container references resolve to roughly 9.3 GB of known logical image size before shared-layer deduplication; five running services reference image metadata already pruned from the Docker image catalogue and must be rebuilt/pulled from exact protected source/pins before runtime cutover. Historical build cache and unused image history are rebuildable and are not an authority that must be copied into the encrypted runtime vault.

## Capacity decision

The initial preallocated sizes are bounded by current payload, growth headroom and rollback coexistence:

- database-vault: 16 GiB;
- operations-vault: 8 GiB;
- local-backup-vault: 16 GiB;
- container-runtime-vault: 64 GiB, built cleanly rather than copying historical containerd state;
- host-state-vault: 32 GiB.

Total FR-06C preallocation is 136 GiB, leaving approximately 176 GB of root free space from the C1 observation before later cleanup/reclamation. Every apply operation must recheck capacity immediately before allocation; these values are not unconditional authorization.

## Required order

FR-06C must remain short and reversible:

- **C1**: inventory, threat/consistency contract and sequencing only.
- **C2**: database-vault source, isolated migration/recovery rehearsal, protected CI, then separate production cutover with a fresh encrypted R2 recovery point. Raw online PGDATA copy is forbidden.
- **C3**: local-backup-vault plus Redis/operations handling. Redis may be rebuilt empty/reconciled from durable authorities instead of copying stale queues. Backup migration is independently reversible.
- **C4**: prove caches contain no durable user authority, wipe/rebuild them from pins, then construct a clean container-runtime-vault with only the exact required runtime images and no plaintext fallback.
- **C5**: host-state migration, volatile/encrypted log policy, random-key encrypted swap and sensitive temporary-data controls. The management bootstrap exception must stay minimal and be explicitly risk-recorded rather than silently called encrypted.
- **C6**: real host reboot/recovery acceptance with all seven FR-06 vault domains, independent recovery evidence, p95/health/backup/restore checks, then and only then close FR-06.

## Safety rules

- No live database copy while PostgreSQL is running.
- No plaintext fallback mount when a mapper is absent.
- No production key persists on the unencrypted root.
- No blind containerd copy or blind Docker/system prune.
- No deletion of old source data until the scoped rollback window, fresh encrypted backup and independent restore proof all pass.
- No claim of full-disk encryption: the design protects closed selected vaults, not a live authorized root user and not every byte of the boot/root filesystem.
- The MCP control plane must remain independently reachable during boot recovery; any plaintext bootstrap credential retained solely for that purpose is a documented residual risk for FR-23, not hidden as a PASS.
