# FR-06C5D7B3 — Permanent scan-execution registry foundation

## Scope and status

This source part adds a PostgreSQL registry and internal transaction helpers. It
is **not a worker rollout, runtime-resource integration, API-route deployment,
actual process/thread/ZAP cleanup acceptance, or completion of D7/FR-06**.
The existing worker does not call these helpers in this part. The authority
remains schema 6 (partial scan-request coverage); no coverage claim is widened.

## Durable contract

Migration `20260918_0053` creates `security_scan_executions`. The historic
bootstrap can already create the table from current model metadata. In that case
the migration reflects and compares its columns, constraints, keys and indexes
against a private frozen temporary reference. Incompatible existing tables are
rejected, not silently adopted or replaced. Existing rows are preserved.
Registration locks
and revalidates pristine backlog, then atomically changes the business scan and
publishes a unique execution owner. It rejects post-hoc adoption of running,
failed, completed, touched, or previously owned scans. Ownership binds an
execution, scan, worker incarnation, admitted generation and private nonce.
Callers may start I/O only after their own transaction commit is acknowledged.
A separate one-time begin rechecks admission, generation and the matching scan.

Resource intent is persisted before use. Each bounded record has a fixed kind,
state, allowlisted metadata and explicit settlement evidence. Started resources
cannot be reclassified as never started. A terminal-looking scan, a timeout,
lease expiry, cancellation acknowledgement or empty result is not settlement.
Resource settlement is monotonic. Heartbeat expiry does not delete, transfer,
release or replay work. The registry has no deletion/automatic takeover API.

An exclusive, nullable unique engine identity serializes cooperating future ZAP
owners. Uncertain remote submissions retain this identity. This database lock
**does not yet serialize the unmodified deployed ZAP adapter**, and no remote
request, stop or engine-cleanup operation is implemented or tested in this part.

Operation return and supervisor return are separate persisted observations.
Reconciliation consumes these existing observations and settled-resource proof;
it never fabricates proof, reruns a scan, clears unfinished work because it is
old, or performs remote cleanup. The ledger has no cascading business foreign
key, so deletion of a business scan does not erase unfinished resource evidence.
Downgrade refuses to destroy the new evidence table.

## Cancellation and observation

The internal cancellation helper is tenant-scoped and leaves the caller in
control of commit/rollback. Its eventual HTTP caller must separately authorize
the actor. It records intent for owned work, cancels only pristine unclaimed
backlog directly, and treats legacy/unknown rows as reconciliation blockers.
No new HTTP cancellation route is exposed by this part.

When both rows are needed, lock order is business scan then execution. The
snapshot reads the registry and business inventory in one REPEATABLE READ
transaction, avoiding a claim disappearing between two READ COMMITTED queries.
Snapshots omit the nonce, expose legacy/unverified blockers, and always retain
`coverage_unverified=true` and `full_host_closure=false`.

## Verification boundary

`test_fr06c5d7b_execution_registry.py` runs against random schemas in an explicitly
test-named disposable PostgreSQL database. It covers schema shape, preserved
migration evidence, atomic registration, duplicate/legacy claims, wrong owners,
one-time begin, generation fencing, cancelled requests, lock races, heartbeat
expiry, malformed records, terminal-with-live-resource blockers, retained engine
ownership, and concurrent resource writes/reconciliation.

Resource observations in these tests are **synthetic inputs**, not measurements
from an actual process, thread or ZAP daemon. The tests trap runtime I/O. Passing
these tests does not close the runtime integration gate. Source test receipts,
checks, commit identity and current status belong in the canonical Project Hub
runtime report, not an invented fixed success count in this source contract.

## Remaining D7 work

The actual scanner worker must adopt the registry and heartbeat/supervisor
protocol, every local and remote resource adapter must record intent and actual
completion/cleanup, cancellation needs an authorized HTTP route and real joined
execution, and uncertain remote/host resources need evidence-based recovery.
These changes need their own actual process/thread/engine cancellation and
cleanup tests before coverage, deployment or D7 completion can be claimed.

No production migration, container replacement, vault transfer, Cloudflare
change, target scan or provider request is authorized by this source receipt.
