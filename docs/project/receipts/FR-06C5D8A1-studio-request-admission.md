# FR-06C5D8A1 — Studio request admission only

## Scope and source boundary

This is the first bounded part of FR-06C5D8A-Studio, based on accepted main
`6e65d162e1db7d91684a34feab8cf73ab51c0ec6` (PR #723).
It does not close FR-06, Studio execution ownership, or the full host drain.

The shared Studio queue producer now checks durable host-maintenance admission
before workspace/project lookup, governance-policy reads, pending autoflush, or
queue mutation. This covers the normal job and legacy synchronous generation
routes. Revision creation also checks before reading the source asset; retry
checks before taking its business row lock or changing a job back to queued.
The shared authority lock remains in the caller transaction through publication.
Closed, absent, old-scope, malformed and unknown-future authorities fail closed
with fixed 503 responses; database-driver details are not returned.

The application's other `StudioJob` constructor belongs to
`realtime_media_runtime.finalize_completed_recording` and explicitly writes a
completed recording result, not queued work. A source contract distinguishes
these two writers. Recording finalization, existing result reads/downloads, and
cancellation retain their prior behavior; request closure does not certify any
of their execution or cleanup semantics.

## Authority and migration

`20260918_0054` follows `20260918_0053`. It advances only a validated schema-6
authority to schema 7 with `studio_job_requests` appended to coverage. The exact
operation, reason, control timestamp, enabled/closed state and unfinished jobs
are preserved; generation advances. Malformed or missing rows are not reseeded.
Downgrade retains the widened authority rather than reopening or deleting it.
Validation is frozen in the migration, not imported from mutable application code.
The runtime head tests now require `0054` and reject both `0052` and `0053`.

Schema 7 is request-only partial coverage. Older applications may fail closed on
it. A coordinated, separately verified deployment is required; this change is
not a command or authorization to migrate the production database now.

## Local acceptance on the candidate source

- 52 new PostgreSQL cases passed in isolated per-test schemas: open requests,
  all four closed/unavailable producer routes, preserved reads/cancellation,
  pending-autoflush rejection, sanitized driver errors, migration retention,
  and actual producer INSERT/UPDATE rollback and close/commit lock races.
- The combined relevant backend regression suite passed **200 tests**. It
  includes existing Studio generation/revision/attachment/safety behavior,
  governance and media APIs, asset snapshots, prior scan admission, shared
  authority and migration-head requirements.
- 14 focused repository contracts passed, including the complete classification
  of the two application StudioJob constructors and nonblocking finalization.
- Full backend Ruff passed. Full application mypy passed on **276 source files**.
- Migration from an empty isolated PostgreSQL database through `0054` passed.
- The lab has its own internal Docker network, synthetic test database and Redis,
  no published host ports, no production credentials and read-only source mounts.

Local limitations and retained failures are not converted into passes:

1. The initial activity-based lock observer timed out
   after 32 passing cases. The corrected observer captures the exact closing
   backend PID and waits for its ungranted PostgreSQL lock. All nine close/commit,
   failure and cancellation race cases then passed, including real flushes.
2. The expanded old-head negative case first exposed a hardcoded error-message
   expectation. It now checks the parameterized rejected revision; the full
   relevant 200-test suite was rerun successfully.
3. The attempted full repository suite on the read-only source mount stopped at
   a pre-existing test that writes a temporary file in its repository root:
   353 passed, 1 skipped, 1 failed. An attempted independent writable-copy harness
   was blocked before execution and was not rerouted. Full repository acceptance
   must come from the ordinary GitHub CI workspace; it is not locally claimed.
4. The first constructor contract assumed all StudioJob constructors enqueue.
   Source review identified the separate completed-recording finalizer. The
   corrected contract explicitly pins both writers and their statuses; it does
   not broadly exempt unknown future constructors.

Runtime evidence is retained under
`docs/project/runtime/fr06c5d8a1-20260918/` in the canonical project hub.
No new CI success, merge or deployment is claimed by this candidate receipt;
those transitions require their own exact-SHA runtime journal evidence.

## Next bounded part — D8A2

Still required: `claim` and `claim_by_id`, durable single-start ownership,
legacy/unproven attempt retention without automatic replay, actual archive and
artifact-store thread completion, cleanup, cancellation intent and resource
settlement/snapshot across generations. Existing stale-claim/retry and
cancellation behavior is **not certified safe by this request-only change**.
Remaining worker families, LiveKit, production ZAP containment, full-host drain,
coordinated migrations/images, fresh backup/restore acceptance and C5D cutover
remain open. No production restart, migration, Cloudflare change, vault transfer
or automatic retry/reconciliation is performed in this part.
