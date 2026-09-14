# FR-06B1 — Asset-vault copy, recovery, and fail-closed proof

Date: 2026-09-14

Source baseline: `6ac557a77f9674805844ce3ddea0be0d540d0e11`

## Architecture refinement

The eleven FR-06B roots must not share one executable mount. Ten passive
authoritative roots remain in `asset-vault` with `nodev,nosuid,noexec`.
`project_execution_data` moves to a separate `project-execution-vault` with
`nodev,nosuid`, because the governed project worker creates a Node project and
runs `npm ci` and `npm run build` inside that root. This keeps execution away
from passive user/media roots without breaking the accepted project workflow.

Docker exposure uses mapper-backed local volumes and Compose
`volume.subpath`. A plain host bind below a vault mountpoint is forbidden
because an absent mount could silently become a plaintext fallback.

## Isolated live-source proof

The reproducible lab created two 256 MiB non-sparse LUKS2 files under
`/var/tmp`. Independent active and recovery keys existed only on tmpfs under
`/dev/shm`. Production Docker volume roots were exposed to the lab through
temporary read-only bind mirrors; the lab did not write to them.

The stable copy covered all eleven roots:

- 331 directories;
- 250 regular files;
- 54,520,640 payload bytes;
- no symbolic links, hard links, or special files accepted.

`asset-vault` contained ten roots, 27 files, and 28,588,887 bytes.
`project-execution-vault` contained one root, 223 files, and 25,931,753 bytes.

Every root required source-before = source-after = encrypted candidate. The
first `course_package_data` attempt observed a concurrent metadata change and
was rejected; the second attempt was stable and matched. All other roots
matched on the first attempt. The retained receipt stores only counts, byte
totals, and aggregate hashes, not user filenames or contents.

The successful rsync attempts copied the 52.00 MiB payload in 0.611237 seconds
(85.065 MiB/s). This is an online nonauthoritative pre-seed feasibility result,
not the final stopped-writer p95 cutover benchmark.

## Docker and recovery proof

The isolated probe established that:

- Compose 2.40.3 accepts and runs mapper-backed `volume.subpath` mounts;
- direct execution from passive `asset-vault` fails under `noexec`;
- the explicit project-vault execution exception works;
- after both mappings close, the scoped container fails to start and the
  Docker volume underlay remains empty;
- wrong keys fail for both vaults and closed raw images reveal neither probe
  marker;
- independent recovery keys reopen both vaults and all eleven recovered
  manifests match the stable source manifests.

Both private LUKS2 header backups, test keys, mappings, mounts, Compose
containers, Docker volumes, and temporary files were removed. Production
container IDs remained unchanged. No production service was stopped or
restarted, no Compose or production volume changed, no live block device was
formatted, no reboot occurred, and Cloudflare was unchanged.

## Boundary and next step

FR-06B1 proves the split design, safe online pre-seed, recovery, least
privilege, and missing-mapper failure behavior. It does not claim live data is
encrypted, does not authorize cutover, and does not close FR-06B or FR-06.

FR-06B2 must add the protected Compose cutover source and exact writer and
rollback matrix, and must not claim that a standalone systemd target gates
Docker's independent restart path. Live provisioning remains blocked until a
fresh encrypted R2 recovery point, external production keys and off-host
headers, an independent owner alert, a stopped-writer final delta, the p95
gate, protected CI, isolated boot/Docker-restart rehearsal, selective service
rehearsal, and rollback with retained read-only plaintext sources are all
evidenced.
