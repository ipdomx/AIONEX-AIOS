# FR-06C5D7B6 — joined execution and conservative remote-engine ownership

Source base: PR #720 merge `0e26a756b1a0486ebf8de312d3fa51678d226f7b`.
This receipt supersedes only the temporary *not wired yet* boundary in the registry
foundation. The historical FR-06C5D7B3 receipt and its synthetic-only scope remain intact.

## Implemented source contract

The worker atomically registers its incarnation and one-time capability before I/O.
It does not hold the business scan row lock over scanner I/O. Cancellation uses a
short tenant/requester-authorized transaction and returns HTTP 202 with intent,
not immediate lease clearance. Claimed cancellation can settle only with no-start
proof; ambiguous claim/begin/commit acknowledgement cannot authorize replay.

The scan operation and heartbeat supervisor are joined separately. Result storage
and operation-return proof share one transaction; lost completion acknowledgement
cannot cause another external execution. Unbound executors retain a blocker.

Thread futures are shielded until actual callable completion. Temporary workspaces
are cleaned by joined tasks. A private gated Linux child subreaper captures and
reaps descendants including setsid/double-fork/new-group children before a private
pipe reports ECHILD. Adapter output is never a cleanup certificate. Registry proof
now requires descendants_reaped in addition to leader/group/cleanup observations;
old group-only process evidence fails closed.

The optional ZAP adapter reserves a durable exclusive engine fence before any
remote request. Mutations persist submission intent before dispatch and preserve
known IDs even when caller cancellation interrupts acknowledgement. Only naturally
completed, acknowledged producers plus fresh explicit empty inventories and session
cleanup can release that engine. A stop acknowledgement is not settlement:
timeout, missing inventory, unknown submission, foreign work or uncertain transport
retain the fence for operator reconciliation. No stopAll, guessed adoption,
lease-expiry release or automatic reset/replay is introduced.

## Verification scope and evidence

The actual executions and their results are recorded in the canonical runtime
receipts under docs/project/runtime/fr06c5d7b6-20260918. Tests include disposable
PostgreSQL, real joined threads/processes/workspaces, concurrent ownership and
cancellation, and an explicitly synthetic HTTP ZAP protocol model. The HTTP model
alone is not real-JVM, daemon filesystem or production acceptance. Failed initial
runs remain retained, not rewritten as successes.

## Deployment and remaining host-level boundaries

No production deployment, production migration, vault transfer or Cloudflare
change is performed by this source part. Neither CI nor source merge means that
production uses this code. A surviving/unobserved process or ambiguous remote job
remains a blocker; request cancellation/timeout is not a host-drain certificate.
Permanent host inventory still reports coverage_unverified=true and full_host_closure=false.
Production ZAP containment and reconciliation of legacy/ambiguous work must be
accepted with exact runtime evidence before any full-host cutover or FR-06 closure.

## Draft acceptance status (2026-09-18)

This source is NOT approved for merge or deployment. The focused four-file run
recorded 164 passing cases and one stale claimant-incarnation test failure. That
test was corrected without weakening ownership; its subsequent run together with
the owned-ZAP HTTP-model suite passed all 71 cases. Ruff and focused mypy on ten
application files passed. These are separate scoped runs, not a claimed successful
full-suite run of the final tree.

The complete repository suite failed three tests because the existing zero-dead
audit reports four bare-pass statements in runtime/supervisor code. The proposed
explicit-handling correction was denied by the tool before execution and was NOT
applied or retried by another route. Fix those findings and rerun all gates before
marking this PR ready. The local full backend run exceeded transport observation;
its final status and cleanup are not certified. The attempted labeled-QA cleanup
was also denied before execution. Existing focused QA runs separately confirmed
their own cleanup. There is no real ZAP JVM acceptance in this receipt.
