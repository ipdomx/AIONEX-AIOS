# FR-06A — Host encryption contract and isolated LUKS2 proof

Date: 2026-09-14

Source baseline: `49075990f7d526a7db0d69944fb74f9cceafa06b`

## What was established

The production RAID1 root is ext4 without dm-crypt. PostgreSQL and WAL, all
Docker named volumes, local backup artifacts, Docker JSON logs, journald,
temporary paths, operator/application secrets, container writable layers, and
the 8 GiB swap file therefore require explicit FR-06 treatment.

The selected path is preallocated file-backed LUKS2 domain vaults. It avoids
repartitioning or reformatting the live RAID and keeps assets, database,
operations, local backups, container runtime state, and host secret/log state in
separate rollback domains.

The current host has no TPM. Unlock material must not persist on the same
unencrypted root; the initial secure mode is manual operator injection into
tmpfs after boot. Services fail closed until their required vault is mounted.
A same-disk unattended key was rejected because it would defeat protection
from offline disk or provider snapshots.

## Isolated proof

The reproducible lab created a 384 MiB regular file under `/var/tmp`, placed
active/recovery/wrong test keys only in `/dev/shm`, and used:

- LUKS2 with `aes-xts-plain64`, 512-bit XTS key, and Argon2id;
- ext4 with `nodev,nosuid,noexec`;
- active-key and independent recovery-key opens;
- wrong-key rejection;
- closed-image raw plaintext-marker rejection;
- LUKS header backup, keyslot erase, header restore, and checksum recovery;
- cleanup checks for mappings, keys, mounts, and temporary files.

All checks passed. No live block device was formatted, no production mount or
service was touched, no reboot occurred, and Cloudflare was unchanged.

The direct-write feasibility measurement was:

- plain ext4 file: 245.835 MiB/s;
- file-backed LUKS2/ext4: 202.725 MiB/s;
- encrypted/plain ratio: 0.8246.

Read comparison was intentionally omitted because loopback cache layers made it
misleading. This result is not a production SLO.

## Boundaries

FR-06A is a design, inventory, and isolated-proof slice. It does not claim that
production data is now encrypted, that the root disk is fully encrypted, that
unattended reboot is safe, or that FR-06 is complete.

The next controlled slice is FR-06B: build the asset vault, perform an isolated
copy/checksum/recovery rehearsal, then propose a selective cutover with the
original volumes retained read-only for rollback.
