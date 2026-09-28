# FR-06C5D10B — Downstream worker cycles outside the claim fence

Base: PR771 merge `564d5754c7a6c5780d77ff09cab327e1ba413364`.
This receipt records source and disposable-database acceptance, not deployment.
FR-07 remains complete. FR-06 and full-host cutover remain open.

## Implemented boundary

D10A fenced eleven media claim methods and six lease-reaper entrypoints. Three
worker-cycle paths could still do other work: arm an approved open song after a
provider balance read, advance dubbing pipelines after a claim returned no work,
and delete expired 3D artifacts before attempting a claim.

D10B fences all eight transaction entrypoints in these three methods using the
same existing Studio maintenance authority. Closed, unavailable, missing or
unsupported authority prevents queue reads, policy initialization and new work
at these boundaries. The helper neither repairs nor widens the authority schema.
Each transaction rechecks admission after any prior discovery/refresh transaction
has ended. Reopening remains an explicit separate operator operation.

The song balance read now occurs under the same shared maintenance lock and
execution-row lock as the eventual arm, after validation of the recorded cost
approval. It is bounded by a twenty-second coroutine timeout. A close must wait
or fail its existing lock timeout; it cannot overtake the balance/arm interval.
Two competing song workers cannot double-arm or perform duplicate balance reads
for that planned execution. No provider submission is added by this change.

All four dubbing advancement branches revalidate in their own transactions,
including the new final pipeline after a separately committed speech refresh.
Already committed speech progress is retained if closure prevents the next step.

The 3D cleanup guard precedes policy initialization and all storage access. An
additional test exposed that cancelling the outer coroutine released its SQL
transaction while the storage thread continued. The cleanup now uses a single
shielded child task: outer cancellation is deferred, including repeated
cancellation, until the already-started cleanup settles and its transaction ends.
Cancellation is then propagated; no second cleanup is started. This does not
claim safe recovery from process death or independently cancelling the child.

## Executed acceptance

The first test import used an incorrect package name and failed before test
collection; the original error and resource cleanup receipts are retained. After
correcting only that fixture import, the unmodified application failed **23 of
25 tests**, including an actual synthetic retention callback invoked while
maintenance was closed. The initial fence passed the same 25 cases.

Expanded review reproduced the cancellation/thread gap as **one failure among
35 cases**. After the cancellation correction all **35 cases passed**. Tests use
real PostgreSQL transactions and observe actual `pg_stat_activity` lock waits.
Provider balance and storage callbacks are explicit test doubles, not real
provider requests or customer files. They cover missing/malformed/old authority,
closed queues, preserved approvals and expired artifacts, normal open-state
behavior, concurrent song workers, closure between separate transactions,
timeout/cancellation rollback and cleanup-thread cancellation.

The combined existing media, 3D resilience/provider-policy and D10A/D10B suite
passed **333 tests** without errors or skips. This total includes the new 35 and
the D10A cases; totals must not be added as independent tests. When the regression
output directory was already present, the invocation refused to overwrite it;
its successful execution/XML/source-hash/cleanup receipts were inspected and
reconciled instead of silently overwriting history.

Runtime evidence is under:
`docs/project/runtime/fr06d10b-media-cycle-fence-20260928/`.
Only specifically labelled disposable resources were removed. No production
record, service, provider inventory, DNS or tunnel was changed for these tests.

## Remaining release conditions

Protected candidate checks, exact post-merge main acceptance and source/image
provenance precede any deployment. Old running workers are not covered merely
because this source merged. Their upgrade requires a bounded, owned and tested
coordinator that serializes admissions and proves quiescence before stopping
unfenced processes. A single zero-count read is insufficient.

This part does not guard every direct producer/arming API, Telegram producer,
previously claimed provider request, file publisher or callback. It does not
settle legacy `needs_review`, certify cancellation of remote work, or authorize
any host-state cutover. The previously blocked Replicate inventory remains
UNKNOWN and was not retried by another tool or path. The canonical Project Hub
journal remains the source of actual deployment and parent-batch completion.
