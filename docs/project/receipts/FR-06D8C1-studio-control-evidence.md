# FR-06D8C1 — Retained evidence fences cancellation and explicit retry

Base: accepted PR #731, `3655b75a204965bf787840acb151c0c1b3b7063a`.
This source increment fixes Studio control classification. It is not cancellation
settlement, post-crash cleanup, production deployment or full-host drain.

## Defect and bounded change

The previous cancellation/retry handlers considered only mutable StudioJob
fields when deciding whether work had never started. Six retained PostgreSQL
regressions demonstrated the defect: an independently retained execution,
publication or success-settlement row was ignored after the job fields were
reset. Cancellation returned `cancelled` instead of `cancel_requested`, and retry
returned 200 instead of 409. This does not establish duplicate worker execution;
worker replay fences were already separate and remain in force.

The helper now reads all three independent ledgers using one existence query,
without filtering by generation, status, row validity or ownership. Any surviving
row is sufficient evidence against a never-started classification. Missing or
unreadable tables fail closed with a fixed 503 response before control mutation.
Neither the helper nor its HTTP error wrapper commits, flushes, deletes records,
starts work, reads file contents or returns ownership nonces.

Both handlers resolve the authenticated tenant's job and acquire its FOR UPDATE
lock before checking history. Locked lookup refreshes the ORM entity after the
lock is acquired and suppresses autoflush, preventing cached job fields from
surviving a competing claim. The original transaction retains the job lock through
commit or rollback. The worker's registration follows the same job-lock contract.

Cancellation with retained history records intent and keeps completion unset;
it does not erase ownership or certify stopped threads or cleaned files. Repeated
cancel_requested calls remain idempotent. Cancellation remains available while
new-request admission is closed. Explicit retry retains the maintenance-admission
check before the tenant job lock and rejects any surviving ledger before resets.
An actually never-started cancellation without history retains its normal retry
path. Tenant-hidden and missing jobs return 404 before reading history.

## Acceptance observations

- The original 18 helper checks and all six unchanged regression assertions now
  pass together: 24 tests. No xfail, skipped regression or weakened assertion.
- The expanded suite passed 48 tests on disposable PostgreSQL schemas and real
  HTTP handlers. Cases cover each missing ledger, foreign tenants, immutable
  retained history, idempotent cancellation, closed admission, stale ORM state,
  no autoflush and actual claim/control commit and rollback races.
- The first expanded run stopped after 35 passes because its synthetic foreign
  job omitted the mandatory requesting user. The fixture was corrected to create
  a user belonging to that synthetic tenant; the application and original six
  regression assertions were not changed for that fix. The failed log is retained.
- Backend Ruff passed and mypy passed on 285 application files. The isolated
  database migrated through the existing `20260919_0057` head. This change adds
  no migration and does not migrate the production database.

Exact-tree repository tests, the wider Studio regression suite, GitHub checks,
merge, postmerge acceptance, source synchronization and registered laboratory
cleanup are recorded only when observed in the canonical Project Hub under
`docs/project/runtime/fr06d8c1-integration-20260919/`.

## Remaining boundary

Reading retained evidence is not a reconciliation capability. No automatic
settlement of cancelled, interrupted, malformed or historical work is added.
The accepted archive and every independent ledger are preserved. Production
activation, other worker families, realtime, ZAP containment, coordinated image
and schema rollout, verified drain and host cutover remain independent FR-06
requirements. A passing control test does not close those scopes.
