# FR-06C5D10C — Transactional downstream media queue-publication fence

Base: PR771 merge `564d5754c7a6c5780d77ff09cab327e1ba413364`.
This is independent of D10B worker orchestration/retention changes. It edits no
D10B worker file and does not reopen the completed FR-07 batch.

## Why claim-side admission was insufficient

D10A prevents new claims/reaping after maintenance closure, but did not guard
publication of new work into those queues. Before this change, an existing
planned identity execution could be armed and a media graph could publish
claimable render steps while maintenance was closed. Partial revisions also
published another graph. The 3D request handler reached project/input processing
without taking the maintenance lock.

The corrected baseline reproduced 46 failures among 54 real PostgreSQL cases;
eight open-state validation controls passed. The first baseline additionally had
seven test-expectation failures because existing domain errors do not all inherit
ValueError. Those expectations were corrected to their exact existing exception
classes before the second baseline. Neither baseline changed product code.
All failure artifacts are retained rather than relabelled as successful runs.

## Exact scope

`require_media_enqueue_admission` delegates to the existing Studio shared-lock
authority, maps closed/unavailable maintenance to a non-sensitive HTTP503, and
never commits, rolls back, seeds policy, changes the authority schema, or invokes
a provider. Unknown consumers and programming errors are not swallowed.

The guard is the first executable statement at eleven publication entrypoints:

* Eight arm methods: design image, stock speech, transcript, dubbing, music,
  open song, video, and identity media.
* Media graph creation and partial revision. Render steps with `planned` status
  are automatically claimable, so graph creation is not merely a harmless draft.
* The 3D create-job HTTP handler, before project lookup, upload read, object-store
  access, or queue publication.

The same caller transaction retains FOR SHARE until its own commit/rollback.
Closed/missing/malformed or insufficient-version authority prevents queue reads
and prevents autoflush of pending caller writes. A duplicate publication is also
refused during closure; ordinary separate read/status endpoints are unchanged.
Open-state domain validation, billing caps, consent, provider selection,
idempotency and existing no-replay semantics remain in their original code.

## Acceptance executed

* Fixed baseline: 54/54 passed, then expanded suite: 58/58 passed.
* A combined 30-file media/3D/graph/live-API regression suite passed 377 tests with
  no failures, errors or skips. This total includes the new cases; do not sum it
  with the focused suites as disjoint coverage.
* Actual PostgreSQL lock waits establish both orderings: publisher-first makes
  close wait for commit or rollback; closer-first makes the publisher wait and
  then receive503 without changing the queued record. Cancellation rolls back
  uncommitted publication before closure succeeds.
* Actual graph persistence creates exactly one render step on commit and none
  on rollback. An idempotent duplicate while open retains a single graph/step.
* A cached open ORM authority cannot authorize publication after a later close.
* A read-only transaction that cannot take FOR SHARE yields503 rather than an
  open result or a repaired authority.
* The direct 3D handler test proves rejection before its mocked upload/project
  callbacks. Existing open-path 3D tests are included in the regression suite.

All database writes used fresh, exclusively owned disposable PostgreSQL schemas
in tmpfs, with an internal Docker network and no production configuration,
provider keys, customer inputs or live provider requests. SQL and functions were
real; upload/storage boundary callbacks in the targeted 3D case were explicit
test doubles. Test resources were removed and absence verified.

Some execution requests found an existing completed evidence directory. They
were not replayed over that evidence: JUnit, source hashes and cleanup receipts
were reconciled. The runner now locks each named test phase and returns an
existing result only if its full source manifest and JUnit counters match.

Evidence root:
`docs/project/runtime/fr06d10c-media-enqueue-fence-20260928/`

## Boundaries that remain open

This source change is not a production deployment receipt or full-host drain
certificate. It supplements the existing Studio scope and requires explicit
source/image acceptance and safe selective rollout. It does not stop work
admitted earlier, attest remote provider completion, add durable execution
ownership, or prove safe cleanup after a rollback/process crash.

Creating an unarmed provider draft, provider-output publication, notification
publication after request commit, and rollback cleanup remain separate effects.
Other direct producers and administrative retry/cancel paths must still be
accounted for before full host cutover. D10B's cycle fences, unresolved provider
ownership and the actual encrypted host-state move are separate acceptance
requirements. No blocked Replicate account inventory request is retried here.
Production schema, services, Cloudflare/DNS, keys and customer records are not
changed by these source/laboratory actions.
