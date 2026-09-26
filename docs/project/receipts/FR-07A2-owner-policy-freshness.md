# FR-07A2 — Fresh Owner policy reads and non-mutating policy views

Base: PR767 merge `dd0a1bc2f48e958c818b7335cd90a85dc58b70de`.
This is a narrow source correction in FR-07A, not a whole-policy authorization
redesign or Production deployment. The canonical operational state remains
`/opt/AIOS/docs/project/PROJECT-REPORT.md` and its append-only runtime journal.

## Reproduced behavior on the unchanged application

Eighteen executable cases used real PostgreSQL, SQLAlchemy sessions and service
functions, with the FR07A1 fixture's separate synthetic schema per case. The
unchanged application failed 13 cases and passed five, with no errors or skips.
Retaining a policy ORM object across another committed Owner update caused:

- Message, response and project-admission helpers to use a prior enabled policy
  after the Owner had committed suspension.
- Message/response counters, message length and storage checks to use older
  limits; the reverse change could also keep rejecting newly permitted usage.
- A second Owner patch to overwrite other already committed Owner fields and
  lose their version advance even though the second writer took FOR UPDATE.
- A legacy policy view to persist normalization and its version change, and to
  hold a policy write lock after autoflush, blocking another Owner transaction.

These are controlled reproductions, not evidence of a Production user incident.
The suspension/project tests exercise the existing service-level checks, not all
HTTP routes, all subscription plans, or all project-creation paths.

## Minimal correction and preserved behavior

Policy SELECTs now refresh a preloaded ORM identity with `populate_existing=True`.
For an Owner writer, the refresh occurs on the same SELECT that takes the existing
exclusive lock. Normal autoflush is retained so this transaction's own prior Owner
patches are not erased by refresh. Read access returns a normalized policy value
without normalizing an existing persisted row; normalization is persisted only
by the explicit locked Owner-update path. First-use, conflict-safe initialization
of a missing policy remains unchanged and may write its initial record.

There is no new migration, public API field, permission exemption, dependency,
provider transport, payment activity, background job, or deployment change.
Existing FR07A1 account-counter behavior is retained.

## Executed local acceptance

The same 18 policy cases pass after the correction. The combined policy and
FR07A1 counter suites pass 38/38 cases. Controls cover same-transaction Owner
patches, read-after-own-update, rollback, parallel disjoint Owner patches, and
eight simultaneous first readers creating one policy row. Earlier counter tests
cover rollover, concurrent consumption, initialization and per-account isolation.

Each run used one internal Docker network with no host ports, temporary PostgreSQL
storage, synthetic credentials, a read-only application mount, bounded resource
limits, and dropped test-runner capabilities. The three named resources from each
run were removed and their absence checked. No production database, provider or
payment system was contacted. Ruff for the complete `app tests` scope and Mypy for
all 299 application source files passed using the repository's existing settings.
The existing untyped-function note and two dependency deprecation warnings are
retained, not suppressed. Root-suite and protected CI outcomes are recorded by
their actual results in the canonical journal.

Evidence: `docs/project/runtime/fr07a2-policy-freshness-20260926/`, especially
`baseline/`, `fixed/`, `combined/` and the executable `run_isolated.py` harness.

## Exact remaining boundary

Fresh reads under the tested READ COMMITTED transaction semantics do not create a
policy-wide admission fence. A policy already fetched into a local dictionary
before a later Owner commit is not retroactively re-read while an account lock is
being awaited. This part neither cancels already admitted work nor proves immediate
WebSocket/session revocation. Transactional policy-change ordering, per-user/plan
exceptions, daily and per-conversation limits, duration, concurrent project/chat
limits, complete route coverage and dashboard acceptance remain FR-07 work.

PR767 main acceptance and source synchronization are separate from this feature
branch. FR-06's 0064 rollout, TURN activation and full-host drain gates are unchanged.
No full FR-07 completion, production acceptance, or final release is claimed.
