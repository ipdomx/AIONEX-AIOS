# FR-06C3C2 — guarded empty-vault provisioning and header custody

Status: source only. No production vault is created by merge.

C3C2 adds a bounded executor for the two empty C3 vaults. It accepts active/recovery bundles only from the fixed `/dev/shm` tmpfs root, binds them and a fresh recovery receipt to a single-use expiring plan, and can only create two empty mapper-backed LUKS2/ext4 volumes. It has no `rsync`, production backup-data copy, Redis copy/flush, service-stop/restart, log-move, admission, or Cloudflare capability.

Each vault has exactly two LUKS2 keyslots using independent 64-byte keys. The 16 GiB local-backup vault exposes only `backups`; the 8 GiB operations vault exposes only `redis`, owned for the Redis runtime. Both use `nodev,nosuid,noexec`.

Two LUKS2 headers are staged only below `/run/aionex-fr06c3/headers`. A separate helper runs inside the existing Backup Worker R2 authority, accepts only the fixed header filenames, requires new object keys, verifies metadata and a full SHA-256 readback for both objects, and never accepts key material. Recovery proof closes/reopens both empty vaults with independent recovery keys and then active keys while candidate consumers remain zero.

Production provisioning remains blocked until protected CI, exact post-merge main checks, a fresh encrypted R2 backup/restore point, external four-key custody, and an active owner maintenance window all pass. C3D/C3E own data movement after these gates.
