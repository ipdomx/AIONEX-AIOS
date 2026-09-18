# FR-06C5D8A2B1 — Join real Studio threads before propagating cancellation

Base: PR #725, merged as `047407b8dc155109420277c708812f6e27eb6dd8`.
This bounded increment is source-only. It does not close D8A2B, Studio execution
settlement, FR-06 or full-host drain, and does not deploy production services.

## Implementation

The worker's archive-build and artifact-store calls now use the same
`joined_studio_thread` helper. It captures the current context and submits to the
executor once. A strong reference and repeated shielding prevent caller
cancellation from discarding the underlying future. The original cancellation
is re-raised only after the function completes; a late function exception is
retained as its cause. An independently cancelled executor future is explicitly
uncertain, not completion evidence. No timeout, uncancel, replay or success-on-
cancellation path is introduced.

The existing committed one-shot guard is unchanged. Cancelled/interrupted work
retains its owner, remains unavailable for automatic replay and keeps
`cleanup_verified=false`. A successfully written archive whose caller was
cancelled is deliberately retained for reconciliation, not accepted as a final
business result and not described as cleaned up.

This is not the proposed storage publication change. That separate write was
blocked before execution; `studio_artifact_storage.py` was confirmed absent.
No equivalent storage operation was retried or routed around the block. The
existing `production_studio.store_artifact` implementation is unchanged.

## Observed acceptance on the source candidate

- 14 standalone lifecycle cases passed using real executor threads and files,
  including 1/3/16 repeated cancellations, late failure, timeout, preserved
  context, no launch before entry and eight concurrent cancelled callers.
  The independently cancelled-future control is explicitly synthetic.
- Four additional cases passed using the actual Studio worker, PostgreSQL,
  HTTP cancellation endpoint and blocked real build/store functions. A duplicate
  execution is denied while the first thread remains active. After interruption,
  ownership and unverified cleanup survive; retry returns 409. A late successful
  store leaves one nonempty archive awaiting reconciliation.
- The combined Studio/API/governance/database/storage regression suite passed
  228 cases, including all 18 new cases, with no failures or skips.
- 28 repository source-boundary checks passed, including five new checks.
- Full backend Ruff passed; mypy passed on all 278 application files.
- The disposable PostgreSQL database migrated from empty to `20260918_0054`.
  This increment adds no migration and uses no production credentials or volumes.

GitHub checks, main acceptance, source synchronization, full repository tests
and registered QA cleanup are recorded only when observed in the canonical
Project Hub under `docs/project/runtime/fr06c5d8a2b1-20260918/`.

## Remaining before full execution acceptance

Persistent resource ownership and all-generation snapshots; atomic no-overwrite
revision publication; identity-bound file cleanup; cancellation settlement with
PostgreSQL; process-loss and ambiguous commit reconciliation. Existing path-based
storage and cleanup risks remain open. Thread return alone is not durable
settlement, database commit, output acceptance or host drain. No production
migration, restart, vault transfer or Cloudflare change was performed.

Implementation references: Python 3.11 asyncio task cancellation/shielding and
run-in-executor contracts, plus the existing project's Security Lab join pattern.
The current increment deliberately does not change that separate subsystem.
