# FR-06C5D8A2B3 — Studio durable execution/thread ledger

Base: PR #727 merged at `7d2094796524c4f017e518647092222d705ccbab`.
The filename is retained for continuity with the original local draft. The
previous proof defects are corrected and the source has passed the bounded
acceptance below. PR/check/main/synchronization status is recorded only when
observed in the canonical runtime journal, not inferred from this receipt.
This increment does NOT implement filesystem settlement or certify host drain.

## Source implementation

`StudioExecution` and frozen migration `20260918_0055` retain one owner per job
independently of business-row deletion. There is no cascading business foreign
key, and this foundation explicitly forbids `cleanup_verified=true`.

Both claim paths register the owner in the same transaction as the business
claim. One-shot start requires the registered incarnation, nonce and admission
generation. A retained owner prevents replay after business metadata is reset.
Thread intent is committed before executor submission. Store requires a recorded
successful build; duplicate registration is rejected and current cancellation
prevents submission of a new thread. Already admitted work can drain across a
maintenance-generation transition. Failed or lost commit acknowledgement never
permits an executor submission or automatic re-adoption.

Thread observation preserves the original exception/cancellation and its cause
when journal persistence fails or is cancelled. Only the observation-error class
is attached as a note. The committed reservation remains a blocker when its
completion cannot be recorded. `StudioThreadUncertain` explicitly records
unverified completion even if the local function-finished flag happens to be set.
The worker's interruption observer similarly preserves the primary interruption.

Acceptance also discovered and corrected a separate join-helper defect: a
blocking function can itself raise `CancelledError`. That exception must not be
mistaken for a caller cancellation and chained to itself. Its identity and cause
are retained; an earlier caller cancellation still takes precedence with the
function failure as its cause. No cancellation is converted to success.

The worker no longer deletes an archive merely by pathname after losing its
business-row owner. Output is retained for later identity-bound reconciliation.
The repeatable-read snapshot includes every execution generation and orphan
owner, plus unregistered non-pristine jobs. It omits ownership nonces, rejects
malformed or missing evidence, and leaves deployment coverage and full-host
closure unverified. This conservative foundation releases no execution rows.

## Observed acceptance of the corrected source

- 57 resource-ledger cases passed using isolated PostgreSQL and actual workers,
  threads and files where applicable. This includes all 47 cases from the
  original draft plus ten exception/uncertain-completion controls.
- 18 standalone join cases passed, including four new cases for a function's own
  `CancelledError`, its original cause, and one/three earlier caller cancellations.
- The combined registry and join run passed 75 cases. These are a subset of the
  wider regression result, not 75 additional unique cases.
- The wider Studio, governance, API, mobile delivery, media, storage and database
  compatibility run passed 369 cases with no failures or skips.
- Full backend Ruff passed and mypy passed on all 280 application files.
- A fresh isolated database migrated through `20260918_0055` successfully.
- Resumed full repository acceptance passed 1739 tests, including the six new
  source-boundary cases, in a disposable copy checked across 2302 source paths
  and run as uid 65534 with an empty environment. The owned copy was removed.
  The first focused source-contract run had five passes and one false-positive
  substring match against the private preflight test_path.unlink call. That
  assertion now uses AST checks to reject unlink in all non-preflight worker
  methods; application behavior and filesystem tests were not weakened.
- The independent-executor-uncertainty controls inject the uncertainty boundary;
  they do not claim to have forcibly stopped a real thread or drained a host.

Full repository acceptance, CI, merge, source synchronization and QA cleanup are
recorded in `docs/project/runtime/fr06c5d8a2b3-resume-20260918/` when observed.
Local tests used an internal-only Docker network, synthetic credentials, a fresh
PostgreSQL database, and no production environment or data volumes. The runner
was non-root with read-only source and disposable writable test scratch space.

## Retained historical failures

The original local draft `4f3f9324` had 41 passing cases and six added but unrun
cases. A prior combined correction/test operation was blocked before execution.
It did not modify source or execute tests and was not reported as successful.
The resumed, permitted edits fixed the two identified defects and added dedicated
controls. The first new run stopped after 49 successes on the self-cause defect
in the old join helper; its log is retained. After correcting that defect, all
75 focused and 369 combined cases passed. No test was weakened to obtain those
results; the failure is not reclassified as a successful run.

## Still not implemented or deployed

Filesystem resource registration before side effects, exact file/directory
identity evidence, identity-bound cleanup and disposition, acknowledged business
commit reconciliation, supported settlement transitions, cancellation settlement,
and full production containment/rollout remain separate work. No execution row
is released here, including normal successful business results. Legacy completed
recordings remain conservatively classified, not automatically reconciled.

No production migration, container deployment, vault transfer, Cloudflare change
or release closure is established by this source acceptance. The current source /
production boundary is also maintained in `docs/project/PLAN.json`.

Reference contracts: Python 3.11 asyncio cancellation/shield and exception cause
semantics, PostgreSQL repeatable-read isolation, and SQLAlchemy populate-existing.
