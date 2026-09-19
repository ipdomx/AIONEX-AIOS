# FR-06D8C3 — Proven post-start Studio cancellation

Base: merged PR #733, `751d32e377241e10ec19fc697a8b922d10febf22`.

This increment is source-only until protected CI, merge, main acceptance and source
synchronization are observed. It does not deploy containers, migrate production,
delete retained archives, reconcile crashed attempts or close FR-06.

## Boundary

A post-start cancellation may settle only after the live worker has committed its
execution-end observation and marked the business job as requiring reconciliation.
The exact job/execution owner is then re-locked. The terminal receipt is accepted
only when every registered Studio thread is durably `joined` with outcome
`success`.

Three bounded shapes are accepted:

1. execution entered `executing`, but no payload resource was registered;
2. the build thread joined successfully before storage began;
3. build and storage both joined successfully and the independent publication
   journal is `observed`, which proves the no-replace final archive was published
   and the private staging name was removed.

A reserved/unresolved/failed thread, partial publication, conflicting success or
pre-start receipt, unexpected business output row, changed ownership or malformed
evidence is not settled and remains a blocker.

The receipt does not rewrite the raw `studio_executions` or
`studio_publications` rows. A fully published archive is retained; this increment
does not path-delete or infer current disk integrity. Snapshot output distinguishes
post-start cancellation from success and pre-start cancellation while keeping
`full_host_closure=false`.

The internal `StudioResourceCancelled` signal is handled after durable end
observation instead of stopping the worker loop. Generic asyncio task cancellation
is not swallowed and remains interruption evidence.

Migration `20260919_0059` adds a non-cascading
`studio_poststart_cancellations` receipt ledger. It performs no backfill and
refuses destructive downgrade. An existing ledger is accepted only when its frozen
schema matches exactly.

## Local acceptance observed

- 11 focused PostgreSQL/real-worker/filesystem cases passed. They include
  cancellation before the first payload resource, during build, during storage
  after complete publication, failed/unverified resources, receipt mutation,
  business-row deletion, immutable terminal evidence, and migration controls.
- A broader Studio compatibility run across the one-shot, resource registry,
  publication journal, normal-success settlement, C1 controls, C2 pre-start
  cancellation and C3 post-start cancellation passed **367/367** cases on
  disposable PostgreSQL and real local filesystem artifacts.
- Generic task cancellation without API cancellation intent remains unresolved and
  propagates. Failed or uncertain resource evidence does not settle.
- Full empty-database migration through `0059` succeeded.
- Backend Ruff passed after removing one unused test-only import; mypy passed on
  **287 application source files**.
- The bounded source contract passed **7/7** assertions and project-hub validation
  returned `PROJECT_HUB_VALIDATION_PASS`.
- The registered compatibility lab writes its exit code and log under
  `docs/project/runtime/fr06d8c3-acceptance-20260919/`; QA cleanup and repository
  acceptance are recorded separately when observed.

Full repository tests on the final staged tree, protected CI, merge and exact-main
acceptance remain required before this increment is accepted.

## Explicit non-claims

This is not post-crash cleanup, automatic reconciliation of failed work, a proof
that a retained archive should be deleted, a production deployment, production DB
migration, ZAP containment, realtime drain, or full-host closure.

## Protected-CI compatibility correction

The first protected backend run exposed one historical result-binding expectation that still required `cancel_requested` after cancellation had been acknowledged while the publication `complete` event was paused. Under C3, once the publication completes, all registered resources are joined successfully and no business result is accepted, that bounded case is terminally classified as `cancelled` with the archive retained. The compatibility assertion now requires the C3 post-start receipt classification and retained publication while continuing to require that no business asset/revision or result binding is published. Application logic was unchanged by this correction; the exact failing case passed against disposable PostgreSQL before the update was pushed.
