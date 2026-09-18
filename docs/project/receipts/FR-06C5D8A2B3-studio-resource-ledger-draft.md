# FR-06C5D8A2B3 — Studio durable execution/thread ledger (LOCAL DRAFT)

Base: PR #727 merged at `7d2094796524c4f017e518647092222d705ccbab`.
This is an incomplete local implementation, NOT an accepted release candidate,
NOT pushed to a PR, NOT merged, and NOT a production deployment or drain proof.

## Implemented locally

- `StudioExecution` and frozen migration `20260918_0055` retain one owner per job
  independently of business-row deletion. The ledger has no cascading foreign
  key and explicitly forbids `cleanup_verified=true` in this foundation.
- Both Studio claim paths register ownership in the same transaction as the job
  claim. Start requires the registered incarnation, nonce and admission generation.
  A retained row prevents replay even when the business metadata is reset.
- Build/store thread intent is durably committed before executor submission.
  Store requires a recorded successful build. Duplicate operation registration is
  refused; current cancellation prevents a new thread. Existing admitted work can
  drain after the admission generation changes.
- The existing joined-thread implementation remains the execution mechanism;
  thread-return observation does not certify filesystem cleanup or settlement.
- The worker no longer deletes the returned archive merely by pathname after
  losing its business-row ownership. It retains the file and the execution for
  identity-bound reconciliation.
- A PostgreSQL repeatable-read snapshot includes every ledger generation and
  orphan owner plus unregistered non-pristine jobs. Malformed/missing evidence
  fails closed. The output excludes ownership nonces and always leaves full-host
  closure and deployment coverage unverified. Conservative legacy classification
  also includes unregistered completed recordings; it is not final family scoping.

## Observed acceptance (bounded)

The initial 41 tests passed on an isolated PostgreSQL database in 20.05 seconds.
They exercised real worker/archive I/O, both claims, rollback, permanent evidence
after job deletion, prevention of metadata-reset replay, exact-owner identity,
cached-ORM refresh, registration before thread entry, actual joined cancellation
(1/3/16 requests), output retention after HTTP cancellation, 16 concurrent resource
registrations with one winner, all-generation visibility, malformed evidence and
strict migration/collision/downgrade controls.

The empty disposable database migrated through `20260918_0055`. Full backend
Ruff passed and mypy passed on 280 application files at that checkpoint.
Six additional cases were subsequently added but NOT run. They cover claim and
resource commit acknowledgement loss, late observation failure and the actual
snapshot isolation setting. Do not report 47 passing cases or complete backend /
repository regression acceptance. No tests were skipped or relaxed to accept this
local draft; the six new cases await implementation/verification.

## Stop and known review defects

A combined cancellation-evidence fix plus the planned broader Studio regression
run was BLOCKED BEFORE EXECUTION by the tool safety-status layer. The file was
reread and still contains the old exception branch. Neither operation was retried
through another tool or routed into CI. No source mutation from that call and no
regression test run from that call occurred.

1. `owned_studio_thread` currently awaits journal persistence while propagating a
   function error/cancellation. A persistence failure can replace the original
   exception. The added late-observation test expects preservation of the original
   cancellation and its late function failure cause, with a sanitized observation
   failure note. That supporting patch did not execute. This remains a merge
   blocker; the new test has not been reported as executed or passed.
2. Independent executor-future cancellation must never be treated as joined just
   because the wrapper's local `threading.Event` happens to be set. The resource
   wrapper should honor `StudioThreadUncertain` explicitly. This was identified in
   further source review, not verified by a newly executed test. Add a dedicated
   negative test and correct the proof boundary before acceptance.
3. Journal calls, both guard integration paths and old suites still require full
   regression acceptance on the exact final source. The initial isolated tests
   do not establish interoperability with every prior suite.

## Remaining scope

Filesystem resource registration before side effects, exact directory/file
identity evidence, identity-bound cleanup and disposition, acknowledged business
commit reconciliation, supported settlement transitions, cancellation settlement,
and full production containment/rollout are not implemented here. The ledger
intentionally releases no execution rows. No production database migration,
service deployment, vault transfer or Cloudflare modification was performed.

Next continuation: accept/synchronize the already merged #727 after exact-main
checks complete; then review this local branch and resolve the two proof defects
through permitted operations, run all 47 cases plus the new uncertain-future case,
run full regression/static/migration checks, and only then publish a candidate PR.
Do not reimplement #727 or treat this local draft as already submitted.

Reference semantics used in the review: PostgreSQL 16 transaction isolation
(https://www.postgresql.org/docs/16/transaction-iso.html) and SQLAlchemy 2.0 ORM
populate-existing refresh (https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html#populate-existing).
