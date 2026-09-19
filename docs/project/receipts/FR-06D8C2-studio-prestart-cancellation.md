# FR-06D8C2 — Proven pre-start cancellation

Base: accepted PR #732, `2a2f4c65d697e7e2abfad013abd8bf7cee32a7a8`.
This is a source increment, not post-start cancellation, filesystem cleanup,
production activation or completed FR-06 acceptance. GitHub acceptance, merge,
source synchronization and deployment are separate evidence-gated events.

## Boundary

The caller's tenant-scoped job lock and the execution lock fence the worker's
one-shot start. Only the exact active/claimed attempt, unchanged claim timestamps,
empty resource inventory, matching ownership and untouched business provenance
qualify. The receipt, cancelled job and API audit share the caller's transaction.
Original execution evidence remains unchanged. Independent receipts prevent replay
when mutable job fields or other ledgers disappear. Missing, invalid or conflicting
proof stays unresolved. The all-generation snapshot separates this bounded
pre-start case from active work without certifying full-host closure.

There are no file writes/deletions, timers, worker adoption, provider requests,
or automatic reconciliation in this helper. Repeated cancellation preserves the
existing 409 contract for already terminal jobs and creates no second receipt.
Migration 0058 adds a non-cascading receipt ledger, validates any existing table
against frozen DDL, performs no backfill and refuses destructive downgrade.

## Focused acceptance and preserved history

The previous draft passed 43 PostgreSQL/real claim-start/API cases. They cover
both lock-race directions with actual pg_blocking_pids observations, commit and
rollback, commit acknowledgement loss, caller cancellation, independent ledger
survival, mutated/orphan evidence, maintenance closure and migration retention.
Sixteen concurrent cancellation requests produce one receipt. Missing evidence
tables and injected pre-start failures leave the job unchanged. No payload work
was launched by these cases.

The earlier resume did not adapt historical fixtures after a combined source
read was blocked. Its initial mypy attempt also encountered an internal cache
error; a writable isolated cache succeeded without changing dependencies.
Those original outcomes and limitations remain in the runtime evidence rather
than being retrospectively reclassified as complete acceptance.

The compatibility follow-up adds StudioPrestartCancellation to the two existing
fixture table sets, updates migration-head assertions to require 0058 while
rejecting 0057, and verifies that the additional receipt table participates in
the same repeatable-read snapshot. These four test adaptations do not alter
application behavior or weaken assertions about work that already started.

On this corrected source, 75 focused tests passed with no failures or skips.
That run includes the 43 pre-start cases; the counts are not additive. The empty
synthetic PostgreSQL database migrated through 0058. Full backend Ruff passed,
and mypy passed on all 286 application files using an isolated writable cache.

A separate attempt to prepare and launch the expanded local backend regression
was blocked before execution. No result is claimed for that attempt and it was
not rerun through another local tool. Full backend acceptance remains required
from the standard protected CI on the exact committed candidate. Repository
acceptance is recorded independently. No pending CI job is counted as passed.

## Operational exclusions

Cancellation after payload start, interruption/crash reconciliation, legacy work,
identity-bound cleanup, other worker families, realtime and production ZAP
containment remain separate. No production database migration, image deployment,
Cloudflare change or host-vault transfer is performed by this increment.

Evidence directories:
`docs/project/runtime/fr06d8c2-resume-20260919/`
`docs/project/runtime/fr06d8c2-compat-final-20260919/`


## Protected-CI compatibility correction

The first protected backend CI run exposed one historical C1 compatibility expectation: a cached queued row was claimed by the real worker before cancellation, and the old test still expected `cancel_requested`. C2 proves that this exact `active/claimed`, resource-empty attempt can be fenced before payload start. The test now requires `cancelled` plus a retained `StudioPrestartCancellation` receipt and a cleared lease; application code was unchanged by this correction. The corrected case passed against disposable PostgreSQL before push.
