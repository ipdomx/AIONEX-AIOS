# FR-06C5D8B5B — Retained normal-success Studio settlement

Base: PR #730, accepted and source-synchronized at
`b610936ca9451bd07ea9fc303c55cc3c5c46280b`.

This increment implements normal-success settlement only. It does not implement
post-crash or cancellation reconciliation, deploy services, migrate production,
transfer host data, certify current archive integrity or close FR-06.

## Source contract

The worker issues a process-local acknowledgement only after the business-result
transaction commits and its session exits successfully. The capability is bound
to the acknowledging asyncio task and consumed before any settlement attempt.
Neither a completed job row, a timestamp, nor a missing job manufactures that
acknowledgement. It is an internal trusted-process guard, not a Python sandbox.

Settlement first acknowledges execution return, then validates the exact owner,
generation, successful joined build/store threads, complete owned publication,
identity-bound staging removal and immutable job/revision binding. Locks follow
job -> execution -> publication -> asset -> revision and remain held through the
receipt commit. A newer asset head is not used as evidence for an older revision.
No filesystem work or unrelated autoflush is performed by the transactional
validator. There is one receipt commit and no automatic retry.

Migration `20260919_0057` adds `studio_settlements`. Receipts have unique execution,
publication and job identities and no cascading foreign keys to business rows.
An existing table is accepted only if it matches the frozen schema exactly.
There is no backfill or automatic acceptance of pre-existing completed jobs.
Downgrade refuses to discard retained terminal provenance.

Original execution and publication ledgers remain unchanged after settlement;
the accepted archive is retained. A later end-observation is rejected before it
can mutate a settled execution or invalidate its proof. A repeated call, copied
capability or racing receipt transaction cannot create another terminal receipt.
Registration and one-shot start also reject a retained settlement even if the
other ledgers or the job's mutable fields have been removed/reset.

The all-generation, repeatable-read snapshot distinguishes verified retained
archives from unfinished writes. Invalid or orphan receipts remain blockers;
malformed raw evidence fails closed. Business-row deletion cannot erase the
terminal receipt. `coverage_unverified=true` and `full_host_closure=false` remain
explicit even when no known Studio blocker is observed.

Lost business/return acknowledgement cannot create a settlement receipt. A lost
acknowledgement after the final receipt commit still raises to its caller; a
subsequent read may independently validate the already durable receipt. There is
no repeat commit, artifact regeneration, file deletion or inferred crash cleanup.

## Observed local acceptance

The resumed draft and all initial failures were preserved before changes. Seven
missing explicit `None` returns were corrected, and immutable settled-ledger
observations were enforced and tested.

- 61 focused PostgreSQL/real-worker/archive tests passed, including the earlier
  53 cases and eight additional immutability, transaction-race and migration cases.
- Full backend Ruff passed, and mypy passed on all 284 application source files.
- The disposable database completed the full migration chain through `0057`;
  focused migration tests also cover creating an absent ledger, no backfill,
  exact bootstrap reuse, rejected weaker schemas and retained downgrade evidence.
- The first combined acceptance call returned an HTTP 502. The recorded exit
  file, complete focused log and idle runner were then read: exit 0, 61 passed.
  No duplicate test run was launched to replace that transport error.

Full backend and repository acceptance, exact-head CI, merge, main acceptance,
source synchronization and registered lab cleanup are recorded only when observed
in `docs/project/runtime/fr06d8b5b-success-20260919/` and the canonical event journal.
The full backend run is a disposable-database test, not a production capacity test.

## Remaining operational boundaries

Failed, cancelled, interrupted, ambiguous and legacy attempts require separate,
identity-bound reconciliation and cleanup acceptance. Other worker families,
realtime, production ZAP containment, coordinated images/migrations, live drain
proof and the host-cutover acceptance window remain separate FR-06 prerequisites.
No source success here certifies those operations or final release readiness.
