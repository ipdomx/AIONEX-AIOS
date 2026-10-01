# FR-06 — shared execution guard core (local source only)

## Scope and observed gap

Interactive continuation `interactive-continue-20261001T161711732906Z-0e663f7e`
read production HEAD/origin-main `7779f740a81d4fae2167c8441218b69e54cf56f5`
and PR835 head `87d52daee928e4faa9c20c360664517c8321c748` on 2026-10-01.
A bounded tracked-source search found no shared execution-guard implementation.
The existing project_hub journal lock protects report updates, not production or
GitHub effects. Per-component lifecycle locks are not a common executor lock.
The previously accepted source queue remains PR835; its current-head required
checks were observed 11/11 successful, with strict ruleset19771501 active.
No merge, source sync or protection change was attempted by this work.

This independent local source is based on epoch-verifier commit
`eb17d645a73ce3112cf508bc67bd7a7786d16d92`. Neither that verifier nor this core is
installed or integrated with a production caller by this receipt.

## Implemented source contract

`scripts/security/fr06_execution_guard.py` supplies a process-bound context that
holds one nonblocking kernel flock continuously through both fresh observations,
a durable intent, and the caller's bounded effect callback. It never infers
ownership from a PID file, heartbeat age, time elapsed or scheduler metadata.
The directory must already exist as a private owned0700 directory. Lock/journal
files are owned0600 single-link regular files, checked with no-follow opens,
path/inode revalidation and close-on-exec descriptors. It refuses a replaced
root, lock or journal and does not follow symlinks or accept hardlinks.

The append-only bounded journal has exact-schema, sequence and previous-digest
validation, unique effect identities, actual UTC record times, complete writes,
fsync and readback. Partial/corrupt/tampered journals block rather than being
truncated, reset, or silently replaced. An intent without an observed result
blocks all later effects, including after process death releases the kernel
lock. No prior-intent resolver, reset, lease-steal or replay API is supplied.

Both observations occur while the lock is held and must match the expected exact
clean main/source, boot ID, closed maintenance operation and generation. A source,
boot, operation, generation or admission change prevents the callback. A change
after intent leaves explicit uncertainty; the next invocation does not replay.
A callback timeout, failure or unproven result similarly retains uncertainty.
Results contain only an outcome enum and digest of a caller-retained sanitized
receipt. These records are observations, NOT automatic production acceptance.

Forked children cannot use an inherited guard as their own authority or unlock
the parent's descriptor. A guard cannot be reused after scope exit.

## Local test evidence

All I/O is in synthetic pytest directories and owned disposable child processes.
No Docker commands, application DB, external provider, service lifecycle, source
sync, GitHub write, maintenance transition, swap/tmp or reboot is exercised.

- First focused suite:68 tests,0 failures/errors/skips.
- Additional malformed-input cases reproduced8 explicit-error failures in77
  tests (unhashable enum payloads and noncanonical numerical data). They were
  fixed by validated types and normalized fail-closed exceptions.
- Final selected suite:180 tests,0 failures/errors/skips, comprising77 guard,
  88 inherited epoch-verifier and15 existing project_hub cases. The separate
  uncommitted33-test hub repair was NOT included or counted.
- Real Linux child-process tests establish kernel-lock contention, scope release,
  inherited-process rejection and a crash after durable intent followed by a
  successor acquiring the lock but refusing replay. Test-only process termination
  is confined to owned synthetic children, never production.

Final JUnit SHA256:
`387e4c44aec93633cb0aa0a3b041459ab6b2fbb7d06ee4281e828084f59cc6c7`

Preserved failing JUnit SHA256:
`39199ae25d6c269b27b6818d93663ca2d88e28c6f4ddff8703bf6624749a6e9b`

Evidence is retained under the current run's sanitized runtime directory.

## Non-acceptance and required integration

This core has no CLI, installer, arbitrary shell runner, provider client or live
operator. It cannot grant activation authority or bypass an approval/security
refusal. The callbacks remain responsible for all original action-specific
source/check, raw evidence, freshness, authority/transaction and safety gates.
Hashing a fabricated receipt cannot turn it into valid acceptance.

Before production use, protected source review must cover fixed callers for BOTH
the primary executor and watchdog (and interactive effects), binding the SAME
accepted private directory. Provisioning/rollout needs an authorized bootstrap
procedure; no ad-hoc lock creation is considered acceptance. Existing unresolved
pre-guard effects must be reconciled independently. This core does not resolve
historical platform refusals, establish that old runs completed, or allow a
shared branch push/merge merely because local tests pass. It does not defend
against malicious root or another writer deliberately ignoring the protocol.
No lock is held between separate connector calls; fixed callers must keep their
whole bounded effect inside the context and join any owned subprocesses.

The legacy dirty `$dir` receipt directory and other worktrees are preserved.
The incident raw diagnostic file was neither read nor copied. Credential
rotation and usage review remain unverified; this source is not incident closure.
C5D epoch/legacy-receipt adapter integration, composite raw drain acceptance,
C5E production/boot/writer/underlay integration and C6 recovery remain separately
gated. FR-06 and the overall release remain open.
