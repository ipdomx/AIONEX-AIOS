# FR-06B4 production vault gates

FR-06B4 adds the missing production provisioning boundary between the proven
FR-06B1/B2/B3 source and a live cutover. It does not itself stop services, copy
live data, open application admission, change Cloudflare, install the systemd
drop-in, restart Docker, or reboot the host.

The selected layout is a 64 GiB passive-asset vault and a 32 GiB executable
project-output vault. Both are preallocated non-sparse files on the encrypted
container boundary defined by FR-06B1. Each uses LUKS2, aes-xts-plain64 with a
512-bit XTS key, Argon2id, ext4, and two independent 64-byte keys. The passive
vault is mounted `nodev,nosuid,noexec`; the project vault is mounted
`nodev,nosuid` and explicitly rejects `noexec`.

The executor accepts separate active and recovery JSON bundles only as private,
root-owned, single-link files directly below `/dev/shm/aionex-fr06b4-keys`.
It never prints or writes key material to the unencrypted root. A plan is valid
for at most 900 seconds, is bound to exact bundle digests and the accepted main
commit, and requires both a plan-derived confirmation and the fixed production
confirmation. Failure before the success receipt removes only artifacts created
by that invocation.

The two header backups are staged only in `/run/aionex-fr06b4/headers`. A later
operator step runs `fr06b4_header_custody.py` inside the existing backup worker,
using its private R2 credential mount. The helper accepts only the two fixed
header names from container tmpfs, refuses existing object keys, verifies exact
metadata and a full SHA-256 read-back for both distinct off-host objects, and
does not accept key material. The independent recovery-key proof follows, then
the tmpfs bundles are removed. Header or key references, rather than their
contents, are the only values allowed in retained evidence.

The repository includes a Docker systemd drop-in that calls the read-only,
Docker-independent `status --require-host-ready` check on every daemon start.
It is intentionally not
installed by source merge or vault provisioning. Installation is allowed only
after both header read-backs and recovery-key openings pass. Missing mappers,
mounts, ext4 labels, mount options, or subpaths then block Docker before the
daemon starts. Exact Docker volume options are revalidated after the daemon is
available and before any guarded candidate start.

After a host boot, the operator re-materializes only the externally held active
bundle into the fixed tmpfs key root and runs the explicit `unlock` command
while Docker is stopped. The command revalidates the private provisioning
receipt, exact accepted `main`, both non-sparse LUKS2 images and their two-slot
cryptographic contract; it opens and mounts both fixed vaults, verifies the
host-only gate, erases its raw temporary key files, and stops without starting
Docker or any service. The input bundle is removed separately after success.

After all gates pass, FR-06B3B performs the data cutover and stops at
`candidate_started_admission_closed`. Docker restart, host boot recovery,
health, permissions, a fresh backup, governed build, and workload p95 (no more
than 15 percent regression) remain mandatory. Opening admission requires a new,
independent owner decision.
