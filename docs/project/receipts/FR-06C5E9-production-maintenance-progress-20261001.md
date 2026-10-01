# FR-06C5E9 — Production-maintenance progress after protected merge

Date: 2026-10-01 UTC

## Accepted source state

PR #828 merged into protected `main` as `8dba19d85e1f84f0d02c878ee39ae53044efa3c5`.
Its head was `08b4f3560c2a4a393db9a3458306fda4f92208a3`.
All five GitHub Actions workflows associated with the head completed successfully:
Browser E2E Boundaries, Phase 34E Container Security, Security Baseline, CodeQL,
and Final Validation. The server checkout `/opt/AIOS` is clean and synchronized
to the same merge commit.

The accepted C5E9 change adds only the encrypted-swap implementation and its
tests/guest fixture. It does not itself claim Production activation.

## Production maintenance authority

The durable schema-8 host-maintenance authority is closed and unchanged:

- operation_id: `cd5a0e31-a49b-4fdf-b2a6-ac53a7831d17`
- generation: `41`
- status: `closed`
- enabled: `false`
- full_host_closure: `false`
- changed_at: `2026-10-01T00:18:41.916040+00:00`
- reason: `FR-06 C5E/C6 authorized production maintenance`

No later evidence in this receipt is promoted across a different authority.

## Accepted component drain evidence

Studio final drain was accepted under the same operation/generation after two
stable observations. The resulting verifier output is retained at:

`/var/lib/aionex/fr06-final-maintenance/cd5a0e31-a49b-4fdf-b2a6-ac53a7831d17-g41/studio-accepted.json`

It states `process_drain_verified=true` and `full_host_closure=false`.

The reviewed Production TURN credential TTL is exactly 600 seconds. A first
Coturn observation at `2026-10-01T04:50:26.996673+00:00` and a final observation
at `2026-10-01T05:13:34.429867+00:00` both contained two explicit
`udp_allocations=0` samples against the same Coturn process epoch and the same
closed authority. The pure acceptance verifier therefore returned:

- `credential_expiry_verified=true`
- `turn_allocation_drain_verified=true`
- `required_quiet_seconds=600`
- `full_host_closure=false`

The raw and accepted evidence is retained in the same private runtime directory
as `coturn-first.json`, `coturn-final.json`, and `coturn-accepted.json`.
No shorter interval is claimed.

## Final graceful-stop and composite full-host closure accepted

The required final service set is exactly:

- `telegram-worker`
- `user-telegram-worker`
- `operations-observer`

The durable before-evidence bound all three running container IDs to the same
closed operation/generation with `restart_policy=no` and `restart_count=0`. The
accepted stop sequence then recorded a create-before-effect intent for each target,
used one `SIGTERM` only, never permitted a forced kill, and verified the same
container epoch stopped with `exit_code=0`, `restart_count=0`, and `OOMKilled=false`.
The accepted service receipts are retained in the private runtime directory as:

- `telegram-worker-stop-accepted.json`
- `user-telegram-worker-stop-accepted.json`
- `operations-observer-stop-accepted.json`

The shared verifier was rerun against `graceful-before.json` and
`graceful-after.json` and returned `graceful_stop_verified=true` for all three
services on operation `cd5a0e31-a49b-4fdf-b2a6-ac53a7831d17`, generation `41`.
The accepted verifier receipt is `graceful-accepted.json` with file SHA-256
`3d557659968f589dbf08c1a522a72346aabf7a09f791480d36774967e562ea3c`.

The composite full-host closure verifier was then rerun from the accepted Studio,
TURN, and graceful-stop evidence. It returned:

- `studio_process_drain_verified=true`
- `turn_allocation_drain_verified=true`
- `turn_credential_expiry_verified=true`
- `telegram_observer_graceful_stop_verified=true`
- `component_full_host_flags_remain_false=true`
- `full_host_closure=true`
- `production_activation_authorized=false`

The receipt field SHA-256 is
`d8d5ea30b5da23e3f15fc2ef18cb2b595f4d1fbe75490778eb0d6bdd318e1cb6`;
the retained `full-host-closure.json` file SHA-256 is
`e7a97646bf0effd77fbe8631ab5dc6a913f02d05699bab7d83b778bdb15089ef`.
This is full-host drain closure only; it is not C5E kernel-effect authority and
does not claim swap, `/tmp`, reboot, or recovery.

## C5E host read-only preflight

A fresh read-only Production preflight recorded:

- host boot_id: `436d6377-f8e3-4e90-b226-3ddc8acf7bc8`
- MemTotal: 67,323,043,840 bytes
- MemAvailable: 59,103,207,424 bytes
- active legacy swap: `/swap.img`
- legacy swap size: 8,587,268,096 bytes
- legacy swap used: 114,819,072 bytes
- legacy swap encrypted: false
- `/tmp`: current ext4 underlay, not a separate tmpfs
- C5E units installed: false
- encrypted mapper present: false
- production_changed: false
- activation_authorized: false

This is capacity/topology evidence only, not activation authority.

## Source gap discovered after C5E9 acceptance

The current accepted source deliberately still lacks a complete Production
activation/reboot path:

- `fr06c5_memory_encrypted_swap.py` states there is no Production CLI, host
  context reader, boot unit, or full-plan executor.
- `fr06c5_memory_tmpfs_publication.py` states there is no Production CLI,
  writer freezer, or encrypted-swap attestor.
- the transaction order still contains `reload_units`,
  `enable_memory_units`, and `activate_tmpfs` without accepted native adapters.
- the current proposed encrypted-swap systemd service remains inert with
  `ExecStart=/usr/bin/false` and `ExecStop=/usr/bin/false`.

Accordingly, the drain prerequisite is now closed, but no swap, mapper, unit, fstab, `/tmp`, reboot, or recovery mutation is authorized by this receipt. C5E/C6 remain open until protected source changes complete the missing journaled Production/boot integration and bind a short-lived activation authority to the exact accepted host-state, preflight, boot-graph, source commit, boot identity, and current maintenance evidence.

## Status

FR-06 remains in progress. FR-07 remains closed. Studio drain, the real 600-second TURN interval, final graceful stop, and composite full-host closure are accepted under operation generation 41. Production activation remains false; no swap, `/tmp`, reboot, or recovery is claimed.
