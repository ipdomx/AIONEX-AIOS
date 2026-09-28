# FR-06C5D11B — Operations observer ordinary-cycle admission

Base: accepted main `a8c13247d1eacc9e52327c05f2084bcc65b12b91` (PR777).
D11A's two Telegram workers and D10's media workers are already deployed.
FR-07 remains complete. This receipt covers new source/laboratory work only.

## Reproduced boundary

The observer's preflight called the observation implementation, including probes,
sample creation and retention, before rolling back its database transaction.
Rollback does not undo a probe or an external side effect. Normal cycles also
refreshed model evidence, committed observation/alert records and published
notifications without consulting maintenance admission in this worker.

The unchanged-source baseline reproduced eight failures in eleven isolated
PostgreSQL cases: preflight and normal-cycle work ran with closed, missing,
malformed or schema7 authority. Three open-state/safety controls passed. The same
eleven tests passed after the correction; expanded acceptance passed30 tests.

## Implemented scope

`run_observer_observation` requires valid, open schema8 without adding a new scope
or migrating authority. It retains an independent lock-only PostgreSQL connection
through one ordinary cycle: optional model inventory refresh, its durable commit
and notification publication; observation and retention; lifecycle/runtime/credit
alerts; their durable commit and postcommit notification publication. Preflight's
observation and rollback use the same supplemental lifetime guard.

The fence uses its own NullPool engine, never the business connection pool.
Denial constructs no action coroutine, makes no ordinary provider call and leaves
ordinary schedule timers/counters unchanged. Properly closed idle workers keep
their bounded local control-plane health heartbeat. Unavailable admission does
not become open, and programming failures are not relabelled as a successful gate.

Outer cancellation while waiting for admission cancels the waiter normally.
After admission it waits for the one existing action, including started thread
work and postcommit publication, before releasing the lock. No automatic retry,
new provider attempt or detached replacement action is introduced. The independent
engine is disposed after worker shutdown, with Redis cleanup retained in finally.
A stop requested during safety reconciliation prevents a new ordinary cycle.

## Safety is deliberately separate

The existing independent safety transaction still runs and commits before ordinary
admission. It can auto-disarm an invalid/expired live pilot or preserve an uncertain
execution as manual_review while ordinary maintenance admission is closed. These
are protective controls, not new execution or proof of provider settlement.
Their log messages are emitted before ordinary work, so an unrelated refresh or
publication failure does not hide the already-committed safety result.

No growth reconciliation implementation, spending gate, rights/consent check,
provider capability, or retained historical execution is changed by this patch.
This does not authorize real spending in the laboratory: all growth rows belong
to disposable schemas on an internal network with no provider credentials.

## Executed acceptance

* 30 focused cases passed. The eight baseline failures and all intermediate
  results remain retained under the canonical runtime directory.
* 56 combined observer/model-scheduler/security/recovery/growth cases passed,
  including the focused30 and existing real pilot/live-execution reconciliation
  tests. These overlapping suite counts must not be added as separate coverage.
* Actual PostgreSQL lock wait observations prove both orderings: closure waits
  for admitted publication after business commit; a waiting observer sees closed
  authority after the closer commits and performs no ordinary work.
* Repeated outer cancellation does not release admission before an owned storage
  thread finishes. Its success and failure cases execute one real synthetic file
  write and leave no detached observer task. Provider calls/publication callbacks
  are declared test doubles, not claims of real external delivery.
* Actual observer runs use the unmodified pilot reconciler on real disposable
  GrowthControlledPilot rows. An expired armed synthetic pilot is durably
  auto-disarmed while admission is closed, and that same safety transaction
  survives an unrelated ordinary failure when open.
* Admission denial preserves independent sentinel safety audits; cancellation
  while acquiring a lock never constructs the action; stale cached ORM authority
  cannot reopen the fence; a separate engine avoids business-pool starvation.

All test PostgreSQL data used exclusively owned schemas or tmpfs containers;
networks were internal, credentials synthetic, and exact resource cleanup was
verified. No production rows, Telegram bootstrap tests, provider inventory,
public HTTP rechecks, or remote provider execution were used in these tests.

Evidence directory:
`docs/project/runtime/fr06d11b-observer-admission-20260928T1438/`

## Remaining limits

This is not a full-host drain certificate. Safety reconciliation and local health
writes deliberately continue until an explicit final graceful observer stop.
Long-running ordinary work may make a maintenance close time out; a timeout does
not justify releasing the lock early or claiming a successful closure.

Process death, lost database connectivity while I/O continues, independently
cancelled inner tasks, remote ambiguous outcomes and direct administrative calls
outside the guarded worker remain separate reconciliation/admission boundaries.
Provider settlement, observer deployment, final graceful-stop acceptance and the
encrypted host-state move are not proven by these source tests. The blocked
Replicate inventory and prior blocked post-D10 verification/bootstrap laboratory
were not retried. FR-06 stays open; FR-07 and prior deployed subparts stay closed.
