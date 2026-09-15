# ADR-001: FR-06 host-data encryption without live-root reformat

- Status: Accepted for staged FR-06 implementation; refined by FR-06B1
- Date: 2026-09-14
- Decision scope: FR-06 architecture and isolated proofs
- Production data migration: Not performed by FR-06A or FR-06B1

## Context

The production host uses two RAID1 members assembled as `md0`, with `md0p2`
mounted directly as one ext4 root filesystem. There is no dm-crypt mapping, no
TPM device, and no unused partition suitable for a safe in-place LUKS retrofit.
PostgreSQL data and WAL, Docker named volumes, local backups, JSON container
logs, journald, temporary files, application secrets, operator material, and an
8 GiB swap file currently reside on that unencrypted root.

FR-05 protects offsite R2 backup objects with client-side encryption. It does
not protect the live local data, local backup artifacts, logs, temporary files,
container writable layers, secrets, or swap.

The FR-06 constraint forbids reformatting or repartitioning the live root. The
design must remain reversible and must not claim protection from a live root
compromise.

## Decision

Use preallocated regular files as LUKS2 containers, one per operational data
domain, mounted as ext4 filesystems and exposed to Docker through local-volume
definitions that require the expected `/dev/mapper` device.

The planned domains are:

1. `asset-vault` in FR-06B for the ten passive authoritative user, media,
   course, recording, portal, release, ingress, and security asset roots.
2. `project-execution-vault` in FR-06B for `project_execution_data`.
3. `database-vault` in FR-06C for PostgreSQL PGDATA including `pg_wal`.
4. `operations-vault` in FR-06C for Redis and retained sanitized logs.
5. `local-backup-vault` in FR-06C for local backup and restore evidence.
6. `container-runtime-vault` in FR-06C for Docker layers and JSON logs after
   authoritative named volumes move to explicit encrypted domain mounts.
7. `host-state-vault` in FR-06C for secrets, retained journals, and classified
   release/audit state; its unlock material remains external.

This gives each domain an independent maintenance and rollback boundary. A
single monolithic vault is rejected because it would couple unrelated services
and enlarge the outage blast radius.

Each vault uses LUKS2, `aes-xts-plain64` with a 512-bit XTS key, Argon2id key
derivation, a preallocated non-sparse backing file, and ext4. Data-only vaults
mount with `nodev,nosuid,noexec`; executable requirements must be explicit
exceptions, never inherited accidentally.

### FR-06B1 refinement: executable project output

FR-06A grouped all eleven authoritative asset roots under one `asset-vault`.
Source inspection in FR-06B1 established that `project_execution_data` is not a
passive asset root: the governed project worker materializes a Node project and
runs `npm ci` and `npm run build` inside `PROJECT_EXECUTION_OUTPUT_ROOT` for 3D
delivery validation. A `noexec` mount can therefore break the accepted project
workflow, while enabling execution for every media and user-asset root would
weaken the boundary unnecessarily.

FR-06B consequently splits that root into `project-execution-vault`, mounted
with `nodev,nosuid` and without `noexec`. The other ten roots remain in
`asset-vault` with `nodev,nosuid,noexec`. This refinement changes only the
FR-06A asset grouping; the other five planned domains and all key, recovery,
boot, migration, and rollback requirements remain unchanged.

Docker exposure uses local volumes backed by the required mapper device plus
Compose `volume.subpath` for per-root least privilege. Plain host bind paths to
a vault underlay are rejected because an absent mount could silently expose an
empty plaintext directory. If the mapper is absent, container creation must
fail closed.

## Key and recovery decision

No persistent unlock key may be stored on the same unencrypted root. The
current host has no TPM, so the secure initial mode is manual operator unlock
from externally held material injected into tmpfs under `/run/credentials`.
Unattended unlock is not allowed until a separately trusted external KMS or
equivalent mechanism exists.

Every vault requires:

- an active key and independently retained recovery key;
- an off-host LUKS2 header backup, stored separately from the vault;
- add-and-verify-before-remove rotation;
- a tested recovery-key open and payload integrity check;
- no raw key in Git, images, logs, reports, backup objects, or the vault file.

A header backup without a recovery key is not sufficient. Losing the last
verified key is an unrecoverable-data incident.

## Boot and failure behavior

Encrypted-data services depend on a dedicated encrypted-storage target and
their required mapper-backed Docker volumes. If a key or vault is unavailable,
those services remain stopped and systemd records a critical local failure.
They must never start against an empty plaintext fallback directory. Before
cutover, an owner-visible out-of-band alert path must be proved without
depending on the locked vault.

An unexpected reboot therefore boots the host but leaves affected application
services unavailable until an operator unlocks and verifies the vaults. This is
an intentional availability tradeoff: storing an unattended key on the same
disk would nullify the offline-disk threat model.

A real host reboot is not part of FR-06A or FR-06B1. Before live migration,
each scoped group must pass an unlock, mount, ownership/integrity, service
start, service restart, close, and reopen maintenance rehearsal.

## Coverage that must not be omitted

FR-06B covers the eleven authoritative asset roots already identified by
FR-04, split across the two FR-06B vaults above. FR-06C covers PostgreSQL and
WAL, Redis or a proved ephemeral replacement, local backups,
application/Docker/journald logs, application temporary files, Docker
writable-layer spill, application/operator secrets, and swap.

Rebuildable npm, security-tool, and model caches are not migrated as
authoritative data. They must be inspected for user excerpts, wiped, and
rebuilt from pinned sources before FR-06 can close. PostgreSQL sockets remain
ephemeral.

Swap will use a fresh random key per boot because hibernation is not required.
Sensitive application temporary paths move to tmpfs or a vault. Services must
be configured so user data cannot spill into an unencrypted container layer.

## Migration and rollback

FR-06A and FR-06B1 do not migrate live data.

Each live vault uses this sequence:

1. Record source identity, size, file count, and checksum evidence.
2. Create and validate a fresh encrypted R2 recovery point.
3. Preallocate and format the candidate LUKS2 file with external keys.
4. Pre-seed only nonauthoritative data while writers continue.
5. Stop only services that write the selected domain.
6. Copy the final delta and compare integrity.
7. Mount the encrypted target and apply explicit mapper-backed Compose volumes.
8. Start and verify only the scoped services.
9. Retain the original source read-only through the rollback window.
10. Wipe plaintext only after owner-visible acceptance and a second recovery
    proof.

Rollback stops the scoped services, restores the prior Compose definition,
remounts the retained source, restarts the same services, and records the
failed candidate. It does not delete diagnostic evidence.

## Alternatives rejected

- Retrofitting full-root LUKS or repartitioning `md0`: destructive and outside
  the approved live-host constraint.
- fscrypt on the current root: does not by itself solve swap, logs, Docker
  layers, or key placement, and requires a live filesystem policy change.
- gocryptfs or application-only encryption: incomplete for PGDATA/WAL, Redis,
  logs, swap, and writable-layer spill.
- A key file on the current root: defeats protection from an offline disk or
  root-filesystem snapshot.
- Reusing FR-05 backup encryption as host encryption: protects backup objects,
  not mounted production data.
- One executable asset vault for all eleven roots: grants execute capability to
  passive user/media roots without operational need.
- Plain bind mounts below a vault mountpoint: risk an empty plaintext fallback
  when the encrypted mount is absent.

## Evidence and consequences

The isolated FR-06A lab formatted only a temporary regular file under
`/var/tmp`; its keys existed only in `/dev/shm`. Active and recovery-key opens
passed, a wrong key failed, a closed raw-image plaintext marker scan failed to
find plaintext, and header erase/restore preserved payload integrity. All
mappings and temporary files were removed.

The isolated direct-write result retained 82.46% of the plain-file rate
(202.725 MiB/s versus 245.835 MiB/s). This is a feasibility signal only.
Loopback read comparison was deliberately excluded because cache layers made
it misleading. FR-06B/C require workload-specific production-candidate
benchmarks and no more than 15% p95 regression before cutover.

FR-06B1 extends the evidence with two temporary LUKS2 vaults, stable
before/after manifests for all eleven live roots through read-only bind mirrors,
exact candidate and recovery comparisons, a `noexec`/explicit-exec split, and a
mapper-backed Docker/Compose fail-closed probe. It does not create a production
vault, change Compose, stop a production writer, or satisfy the live cutover
gates.

This decision protects closed vaults from offline storage access. It is not
full-disk encryption and does not protect data from live root or an authorized
service after unlock.

## FR-06C1 refinement: containerd runtime store and clean reconstruction

The live C1 inventory on 2026-09-15 corrected the original runtime-size assumption. Docker reports `/var/lib/docker` as its Docker root, but Docker 29 stores image content and overlay snapshots under `/var/lib/containerd` on this host. The retained historical containerd tree was about 398.6 GB while the root had about 322 GB free. Copying that tree into a new preallocated vault while also retaining it for rollback is therefore rejected as an unsafe capacity plan.

Container image layers, old snapshots and build cache are rebuildable runtime material rather than durable user authority. FR-06C will construct `container-runtime-vault` cleanly from the exact protected source and pinned/pullable image authorities after PostgreSQL, Redis, backups and authoritative named volumes are already externalized to their own encrypted domains. Only the images required by the accepted runtime are rebuilt or pulled; historical build cache and unused layer history are not migrated. Five currently running services whose old image metadata has already been pruned must be rebuilt before the runtime cutover, so their running snapshots are never presented as a reproducible recovery source.

The C1 candidate size for the clean runtime vault is 64 GiB. This is a capacity starting point, not an unconditional allocation: the cutover must re-measure required images and free space, build the candidate runtime independently, and prove that it can recreate the complete accepted Compose topology before the old runtime is stopped. Missing runtime mapper behavior remains fail-closed.

C1 also records a narrow bootstrapping boundary for `host-state-vault`: the MCP control tunnel must return before application vault unlock so an operator can recover a rebooted host. Until a separately trusted KMS/TPM-like bootstrap exists, the minimal credential required solely for that out-of-band control channel is an explicit residual risk rather than a false encryption claim. Application/provider/user secrets are not covered by that exception. FR-23 must review and, if feasible, rotate or further isolate the management bootstrap credential.
