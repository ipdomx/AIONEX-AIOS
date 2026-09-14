# FR-06B2 — Compose cutover and rollback contract

Date: 2026-09-14

Source baseline: `a890d4fb1d7ea2a5f05345c7a869edbbd757f191`

## Outcome

FR-06B2 adds a source-only Compose overlay for the two FR-06B vaults. It
does not create an external Docker volume, mapper, vault, key, header backup,
mount, container, or production change. The accepted production Compose file
remains unchanged and is still the rollback source.

The overlay replaces each protected mount by target path, using an external
mapper-backed local Docker volume and long Compose `volume.subpath` syntax.
It never binds a host vault-underlay directory. An absent external volume or
mapper therefore blocks container creation instead of falling back to an empty
plaintext directory.

## Complete consumer coverage

The active production profile exposed 53 protected mounts across 21 service
definitions. Validation with every Compose profile enabled found the dormant
`audio-song-worker-secondary` definition as an additional writer. The
contract and overlay therefore cover all 54 mounts across 22 service
definitions, including definitions that are not currently running.

| Root | Mounts | Runtime-writer mounts | Read-only mounts | Initializer mounts |
|---|---:|---:|---:|---:|
| `three_d_asset_data` | 5 | 2 | 2 | 1 |
| `media_asset_data` | 14 | 12 | 1 | 1 |
| `project_execution_data` | 6 | 2 | 3 | 1 |
| `studio_asset_data` | 4 | 2 | 1 | 1 |
| `course_package_data` | 4 | 1 | 2 | 1 |
| `realtime_recording_data` | 5 | 2 | 1 | 2 |
| `portal_asset_data` | 3 | 1 | 1 | 1 |
| `mobile_release_data` | 3 | 0 | 2 | 1 |
| `audio_song_ingress_data` | 3 | 1 | 1 | 1 |
| `security_source_data` | 4 | 0 | 3 | 1 |
| `security_remediation_data` | 3 | 1 | 1 | 1 |
| **Total** | **54** | **24** | **18** | **12** |

The 24 writer mounts belong to 18 unique runtime-writer service definitions:
`academy-course-worker`, the six primary/secondary audio workers,
`backend`, both design-image workers, `identity-media-worker`,
`media-worker`, `project-worker`, `realtime-egress`,
`security-remediation-worker`, `studio-worker`, `three-d-worker`, and
`video-provider-worker`. The exact per-root service, target, access mode, and
role matrix is retained in
`FR-06B2-compose-cutover-contract.json`.

`backup-asset-root-init` and `realtime-recording-init` are initializer
definitions, not evidence of currently active writers. They are included
because omitting them would let a later initialization path address a legacy
volume. `backup-worker` and `security-scan-worker` are the only definitions
that are read-only across every protected mount they consume.

## Additive and reversible Compose path

`docker-compose.fr06-assets.yml` is applied after
`docker-compose.production.yml`. Compose's target-path uniqueness replaces
only the protected mounts. The overlay:

- uses `fr06_asset_vault` / `aionex-fr06-asset-vault` for ten passive
  subpaths;
- uses `fr06_project_execution_vault` /
  `aionex-fr06-project-execution-vault` only for
  `project_execution_data`;
- preserves every service's existing read-only or read-write mode;
- changes no image, command, environment, secret, network, port, dependency,
  healthcheck, resource limit, or unrelated mount;
- leaves legacy named-volume declarations in the reviewed base file for
  rollback.

The external volume objects and all eleven subpaths must exist before any
container is created. Their driver options and mapper identity are a later
execution gate, not configuration supplied by this overlay.

## Cutover and rollback invariant

A live cutover remains forbidden by this receipt. The minimum sequence is:
close application admission without changing Cloudflare, drain in-flight work,
resolve every scaled container for the 18 writer definitions, stop all writers
and initializers, prove there are no unlisted writable descriptors, stop the
affected readers, perform a stable final delta, render and validate the
overlay, and then start only the affected services while admission remains
closed.

Health, permissions, passive `noexec`, project-build execution, backup reads,
queue integrity, restart behavior, and workload-specific p95 must pass before
admission reopens. A p95 regression greater than 15 percent rejects the
cutover.

Rollback has two distinct cases:

1. Before admission reopens, remove the overlay and recreate only the affected
   consumers against the retained legacy volumes.
2. After any new encrypted-vault writes, first close admission and drain again,
   then perform a reverse stable delta into temporarily writable retained
   sources before removing the overlay. Blindly switching to stale plaintext
   volumes is forbidden.

Neither path deletes the candidate vault or diagnostic evidence.

## Startup-gate decision

FR-06B2 intentionally does not ship a systemd unit. Production containers use
Docker `restart: unless-stopped`; a standalone systemd target cannot gate
Docker's independent restore path and would overstate protection. FR-06B1
already proved the safe property that a missing mapper makes the local-volume
mount fail without plaintext fallback.

Before production provisioning, an isolated boot and Docker-daemon-restart
rehearsal must prove missing mapper, wrong key, delayed unlock, and recovery.
Only then may the project select either a verified manager for the entire
Compose lifecycle or a tested change to restart-policy orchestration.

## Validation

`scripts/security/fr06b_validate_compose_overlay.py` renders the base file
alone and with the overlay under all profiles. It compares the base consumer
matrix to the retained contract, verifies all 54 merged mounts and access
modes, rejects remaining legacy mounts or unexpected vault exposure, and
compares all unrelated service and top-level configuration. It invokes only
`docker compose config` and `docker compose version`; it does not contact the
Docker daemon to create or start anything.

Both the example environment and the current production environment rendered
successfully with Compose 2.40.3. No service, volume, mapper, key, production
file, reboot, or Cloudflare setting changed.

## Boundary and next step

FR-06B2 is reviewed source and read-only render evidence only. It does not
claim that production data is encrypted and does not close FR-06B or FR-06.

FR-06B3 must add and isolate-test the external-key admission, exact
mapper/volume-option preflight, Docker restart/boot gate, final-delta executor,
and both rollback paths. Production provisioning remains blocked until a fresh
encrypted R2 restore point, separated off-host key/header custody, an
independent owner-visible alert, and an approved maintenance window are
evidenced.
