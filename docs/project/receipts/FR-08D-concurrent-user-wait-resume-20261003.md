# FR-08D — concurrent users, queue wait, and restart/no-replay acceptance

This source-only acceptance extends the already-merged FR-08C scheduler without
changing Owner limits or provider routing.

- Every durable conversation dispatch records dispatch_queue_wait_ms on the job
  payload and queue_wait_ms on the dispatch audit event.
- Missing or clock-inverted creation timestamps remain null; they are never
  fabricated as zero latency.
- Restart selection remains status-based: only queued rows are candidates, so
  retained running/uncertain work is never automatically replayed.
- The acceptance fixture proves three queued users remain independently
  schedulable while a pre-existing running row is excluded.
- The provider call still occurs only after the durable running-row/audit
  transaction commits.

No live provider call, production deploy, database migration, billing event, or
customer data was used by this acceptance.

Validation:
- py_compile: PASS
- git diff --check: PASS
- isolated backend-image direct Python harness, network=none, source mounted read-only: PASS
- The backend runtime image does not ship pytest, so no package was installed and no
  unsupported host/environment failure is counted as product evidence.
