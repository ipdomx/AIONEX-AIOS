# FR-07A1 — Existing free-tier quota consistency

Source base: accepted PR765 merge `22e94dc8afe892d5f80a0b71f55bac387ce571c1`.
This independent FR-07 subpart depends on completed FR-01, not on completing FR-06.
Canonical merge/deployment status remains in the Project Hub runtime journal.

## Reproduced defects

The expanded unchanged-source run executed 15 PostgreSQL cases: 7 failed, 8 passed,
with no setup errors or skips. Two failures showed a preloaded ORM account bypassing
a newly consumed message/response limit even after SELECT FOR UPDATE. Two more
showed loss of an already committed increment (two accepted consumptions persisted
as one). A row lock alone did not refresh the identity-map object.

The other three failures showed that reading an expired account's status persisted
a counter reset and acquired a usage write lock through ORM autoflush, preventing
a concurrent consumer from finishing before the status transaction committed.
These tests do NOT demonstrate that an ordinary default-autoflush status request
itself overwrote a concurrently committed counter: that particular read held a lock.
The lost-increment evidence comes from the separately reproduced preloaded-writer path.
All data were synthetic in per-test schemas; no production incident is asserted.

## Minimal correction

Locked account reads now use `populate_existing=True` after taking FOR UPDATE.
The normal application's autoflush semantics preserve earlier writes in the same
transaction before the refreshed SELECT. Both message and assistant counters, and
the shared storage-counter path, receive current committed account state.

A shared pure helper computes the effective usage period. Status reads no longer
mutate an existing account's period, counters or version. Actual rollover remains
in the locked writer transaction. Existing first-use account/policy initialization,
30-day period semantics, owner limits, suspension checks and non-free bypass are
preserved. No database schema, provider transport, payment gateway or deployment
configuration is changed.

## Executed acceptance

Twenty executable PostgreSQL tests cover preloaded-account limit denial, retained
committed increments, expired/invalid-period projection, concurrent reads and writes,
12 competing consumers against an owner limit of five, eight concurrent first-use
consumers, same-transaction reservations, rollback, independent users, storage refresh,
policy suspension and unchanged non-free behavior. All pass on the corrected source.
The first unchanged-source run had 5 failures in 10 cases; it remains retained along
with the expanded 7-failure run. Tests use real service functions, ORM objects, locks
and PostgreSQL transactions, not mocked quota responses.

Evidence is retained in `docs/project/runtime/fr07a-quota-consistency-20260924/`,
including before/after JUnit, runner source, cleanup verification and source hashes.
The runner uses an internal network with no published ports, ephemeral PostgreSQL,
synthetic credentials, read-only application source and specifically owned containers.

## Remaining FR-07 work — not silently closed

The existing Owner API in `app/api/owner/free_tier.py` provides global free-tier
project, rolling-period message/response, storage and length controls. Consumption
currently reaches these helpers from `app/api/v1/endpoints/project_executions.py`.
This repair does not certify all project/conversation creation paths or all plans.

FR-07A still requires the complete policy/exception inventory. FR-07B/C require
per-day/per-conversation duration and message limits, concurrent project/conversation
limits and exception priority. FR-07D must execute WebSocket/reconnect and immediate
revocation tests; connect-time authentication alone is not that evidence. FR-07E
requires both dashboards and a separately accepted production deployment.
No parent-batch completion, capacity certification or final release is claimed.
