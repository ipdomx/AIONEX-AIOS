# FR-06C5D8A2A — Studio one-shot claim/start and cancellation intent

This is a bounded source-safety increment after PR #724 (merge
`933afc83fc04851ba098ddc80929b6555e6f3e35`). It is not complete Studio execution
ownership, a resource registry, a cleanup receipt, deployment acceptance or
full-host drain proof. FR-06 and D8A2 remain open.

## Implemented contract

Both `StudioWorker.claim` and `claim_by_id` delegate to the same transaction.
Admission is locked before the job row; only pristine provider-neutral jobs are
eligible. Old running jobs, old attempts, prior output/error/moderation/provider
provenance, and unknown result metadata are not adopted, reset or replayed.
Filtering happens before SKIP LOCKED so ambiguous queued rows do not starve new
work. The claim persists its incarnation, admitted generation and phase together
with the one-time attempt and existing lease ownership field before returning.

A second transaction checks current admission, the exact claiming incarnation,
unchanged generation and the claimed phase. It commits `executing` before any
build/store I/O is dispatched. Repeated calls, a different worker with the same
nonce, stale generations and unacknowledged begin commits cannot authorize a
second execution. An expired lease is never evidence of stopped work.

Build/storage exceptions and interrupted execution retain an unresolved attempt
rather than automatically resetting it to queued. The first failure evidence is
not overwritten by a later wrapper return. Successful output publication retains
the guard alongside the result metadata; `cleanup_verified` stays explicitly
false even on success. Failed settlement is never inferred from a timeout.

Cancellation of an attempted/ambiguous job records `cancel_requested`, retaining
ownership and leaving completion unset. Repeated cancellation is idempotent.
A never-started cancellation may still finish immediately and may be explicitly
retried. Retry refuses all execution/output/provider provenance, including legacy
terminal rows, rather than wiping evidence. Reads/downloads and completed
realtime recording finalization remain outside request admission. The legacy
synchronous path sanitizes admission closure/unavailability during its claim.

## Local acceptance

- 241 focused backend cases passed together, including 102 new PostgreSQL
  no-replay cases. These cover actual lock waits, claim/start commit/rollback,
  commit acknowledgement loss, generation changes, competing public claim paths,
  sixteen duplicate starts, wrong incarnation, error/cancellation retention,
  retry rejection and a real nonempty local archive/store success.
- 23 repository source-boundary cases passed (14 existing and 9 new).
- Full backend Ruff passed; mypy passed on all 277 application files.
- A fresh disposable database migrated through `20260918_0054`. This increment
  adds no schema migration and does not claim schema 7 as full execution coverage.
- The test PostgreSQL, Redis and runner use an internal-only Docker network,
  synthetic test credentials, no published host ports and no production volumes.
  Source is mounted read-only. Production services and data are not test targets.

The first test run retained 77 successes and a test-harness error calling the
wrong name for the existing reopen function; the call was corrected to the
existing `open_admission`, then all 102 passed. A broader run retained 221
successes and a shell-fixture failure: the disposable runner's `/tmp` was noexec.
The fixture needs to execute its synthetic Docker stub. Only the owned idle QA
runner was replaced with executable disposable `/tmp`; the complete 241-case
suite then passed. Initial runner entrypoint/tool-path/cache configuration errors
are retained in runtime evidence and are not application failures or acceptance.
No production container security setting was changed for these tests.

Evidence lives under `docs/project/runtime/fr06c5d8a2a-20260918/` in the canonical
Project Hub. GitHub checks, merge SHA, exact-main acceptance, source synchronization
and QA cleanup must be recorded there as they actually occur. None is implied by
this source receipt. Full backend/repository CI remains required before merge.

## Remaining work / next bounded implementation

D8A2B still needs permanent resource ownership and snapshots across generations,
joined build/store threads, atomic no-overwrite publication, exact cleanup
ownership, cancellation completion and PostgreSQL-backed settlement. This change
deliberately does not label function return or cancellation as resource termination.
Guarded cancelled work can remain `cancel_requested` pending that settlement;
never manually clear its guard, reset attempts or auto-requeue it.

Do not deploy the incomplete execution family or move host data merely because
this source fence passes. Coordinated image/authority rollout, other producers and
workers, LiveKit/ZAP containment, old ambiguous work, fresh backup/restore evidence
and the host-cutover gates remain prerequisites. No production migration,
redeployment, vault transfer or Cloudflare change was performed for this increment.
