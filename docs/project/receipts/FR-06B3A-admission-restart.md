# FR-06B3A — admission and Docker restart boundary

Status: source-only candidate, isolated rehearsal passed, production unchanged.

## Decision

The protected runtime services cannot retain `restart: unless-stopped` because Docker can restore them independently of any vault admission unit. An isolated negative control also proved that `restart: on-failure:5` is restored when this host's Docker daemon restarts, so that alternative is rejected.

The additive admission overlay therefore changes exactly the 20 protected runtime service definitions to `restart: "no"`. The two initializer definitions remain `restart: "no"`. Every post-daemon-start launch and every retry must be performed later by the guarded FR-06B3B lifecycle, after a fresh fail-closed admission decision.

## Retained source

- `web-dashboard/docker-compose.fr06-admission.yml` changes only the restart field for the 18 writer and 2 read-only-only definitions, across every profile including `audio-song-worker-secondary`.
- `scripts/security/fr06b_cutover_admission.py` provides read-only `inspect-runtime` and pure `evaluate` commands.
- Runtime inspection requires both active ext4 LUKS2 mappers, exact mount options, all 11 safe subpaths, exact mapper-backed Docker local-volume options, zero running consumers, the FR-06B2 54-mount render, and the 20-service restart overlay.
- Production preflight evaluation (never execution authorization) requires fresh protected-branch evidence, a fresh encrypted R2 restore, independent external active/recovery custody, two distinct off-host header references, an independent alert, an approved maintenance window, stopped and drained consumers, exact final delta, both rollback rehearsals, and p95 regression no greater than 15%.
- Embedded secret material and local production key references are rejected. A lab preflight is accepted only with an explicit lab flag. Both lab and production outputs keep `production_authorized: false`; the B3B executor is deliberately absent.

## Isolated result

The retained receipt at `docs/project/receipts/FR-06B3A-isolated-admission-restart.json` was produced on Docker 29.1.3 using a separate socket, data root, exec root, containerd namespaces, and two disposable 192 MiB LUKS2/ext4 vaults.

The rehearsal proved:

- both `unless-stopped` and `on-failure:5` controls restore after daemon restart;
- both `restart: no` mapper-backed candidates remain stopped until a fresh admission and explicit start;
- missing mappers block the gate and container start without a plaintext fallback;
- wrong keys fail for both vaults and independent recovery keys reopen both;
- delayed unlock never starts candidates by itself;
- the stable final delta, retained read-only legacy source, pre-admission rollback, and post-admission reverse delta all preserve exact manifests;
- every temporary key, header, mapper, mount, image, volume, container, socket, and isolated Docker directory is removed;
- production container identity is unchanged.

The isolated receipt deliberately does not claim a host-boot rehearsal, external alert delivery, protected PR/main checks, live workload p95, production custody, or production authorization. Those remain fail-closed production gates.

## Boundary

This batch does not authorize production cutover. It does not create production vaults, keys, or Docker volumes; does not apply either overlay; does not stop or restart production services or Docker; does not reboot the host; does not install a systemd unit; and does not change Cloudflare.

It does not close FR-06B or FR-06. FR-06B3B remains required for the reviewed guarded lifecycle/final-delta executor, followed by the external custody, R2 restore, independent alert, owner-approved maintenance window, protected checks, live acceptance, and rollback-window gates.
