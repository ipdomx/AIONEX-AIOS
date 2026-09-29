# FR-06C5E6 — owned allocated backing lifecycle

## Scope and source

This source part follows C5E5 candidate `2ccb2d14fcede5ea7d8aad7a84b0115baf035a11` (PR #783). It implements `prepare_encrypted_backing` as an allocated private staging file followed by a journal-bound atomic publication. It is not the encrypted-mapper creation step, a boot service or an activation CLI. FR-07 remains complete; FR-06 remains in progress.

## What is implemented

`fr06c5_memory_backing.py` creates a new operation-specific private staging directory and records an fsynced preparation intent and inode receipt before `posix_fallocate`. Both file and directory synchronization must succeed; space must exceed the requested allocation plus an explicit reserve. The candidate is rejected if it is sparse by its allocated-block count, unexpectedly linked, not private, or not the exact retained inode. Allocation failure retains private partial state and never manufactures a completed manifest or retries it automatically.

Publication is one Linux `renameat2(RENAME_NOREPLACE)` with C5E2's durable pending intent. No existing backing is adopted and no foreign destination may be overwritten. The parent, lock, operation bundle, preparation records, manifest, stage and retained file descriptors are revalidated. Names are rechecked after consumer observation. Undo returns the same allocated inode to staging; it does not truncate, unlink, copy or claim secure erasure. Retained staging is intentionally part of the baseline and must be preserved for reconciliation.

`LinuxConsumers` matches actual `LOOP_GET_STATUS64` backing device/inode pairs, not a filename hint, and separately detects a direct file swap. Only a positive ENXIO from the loop-status operation is accepted as an unbound loop. Missing nodes, permissions, extra/inconsistent evidence, changed loop/swap sets and bounded-sampling failures prevent a successful zero-consumer result. Used-page fluctuations are excluded only from the direct-swap inventory comparison, not resource identity.

The unused/staged baseline itself requires a current zero-consumer observation. A review test reproduced two false baseline/restoration certifications in the first new implementation when an independently attached loop was present; both are rejected by the final candidate. Returning a path to staging alone is not sufficient evidence of restoration.

## Acceptance already executed

- 69 directed tests as `nobody`: actual allocation/rename, create-only preparation, reserve and sparse-allocation rejection, preserved ENOSPC/partial preparation, current-context drift, changed file/lock/path/manifest, no raw backing-content reads, kernel-inventory rejection, and four actual test-process deaths before/after publication in both directions.
- Six native cases in a separate Linux 6.8.0-142 QEMU guest. A 16 MiB file created by the adapter backed an actual loop, dm-crypt device and active encrypted swap. Undo was denied while active and still denied by the bare loop after mapper closure; it succeeded only after the consumer was removed and the journal explicitly reconciled. Direct file swap was separately detected and denied. Four guest child-process SIGKILL cases reopened the retained intent, refused blind replay and restored the same allocated inode to staging.
- The guest is a dedicated TCG VM running as `nobody` on the host, with one virtual CPU, 512 MiB memory, no network, host filesystem shares or passed host devices. Only its own virtual disk is writable. It powered off after proving no active guest swap or mapper remained.
- The first expanded unit-test run failed because its test-double sysfs root lacked the path-join interface. This fixture-only failure is retained and corrected; no guard was disabled. Ruff/Mypy findings were corrected in source/tests without changing rules.

Native payloads and launch/console/source proofs live at `docs/project/runtime/fr06c5e6-backing-ownership-20260929/`. The exact candidate source is matched against the guest's copied code before final acceptance. The full Root suite, protected PR checks and main acceptance are recorded separately; a source receipt never declares deployment.

## Boundaries and remaining work

The adapter uses one exact backing step journal. Complete composition with C5E3 configuration files, C5E5 legacy swap, loop/mapper creation, encrypted swap activation, unit enable/reload and tmpfs transitions is not shipped here. It supplies neither a production context reader nor writer quiescence. Advisory file locks serialize cooperating adapters, not arbitrary administrators. Kernel-consumer reads are not an mmap/open-file inventory and do not freeze readers or prevent ABA. Independent closed/frozen writer authority remains mandatory.

A partial preparation is retained and not automatically resumed, removed or loaded as ready. Production preparation recovery and ownership of subsequently created loop/mapper resources remain independently gated. No claim is made of power-loss survival, real host reboot, key custody or full-host/provider drain. The QEMU encryption setup is an explicit test fixture, not a shipped mapper-creation adapter.

No host swap, mapper, mount, systemd unit, maintenance authority, provider or deployed worker was changed by this part. No legacy unsafe operator or previously blocked Replicate inventory, D10 combined verification or Telegram bootstrap test was executed. D10/D11 deployments and FR-07 are not repeated.

## Full source-suite acceptance

FR-06C5E6 source acceptance: 69 focused tests and 2713 root tests passed. Isolated QEMU verified owned backing allocation, consumer fencing, explicit recovery after process loss, and no host swap change. Production activation, host reboot/power-loss, full-host closure, C5D drain, and C6 remain unverified.
The complete Root suite used an owned writable nonroot snapshot; 2,542 source files matched. The original detailed limits and preparation semantics are retained alongside the later acceptance update.
