# FR-06D8C4A — Read-only Studio post-crash observation

Base: merged PR #734, `df8e052cb6b1e081a3fbf8a128cc609c2134223c`.

This increment records durable point-in-time evidence for an unsettled Studio
attempt after maintenance admission has been closed. It is deliberately not
filesystem cleanup, process-drain proof, automatic retry, stale takeover,
production activation, or full-host closure.

## Contract

Observation locks the mutable job and durable execution/publication evidence,
requires PostgreSQL and the existing Studio maintenance scope to be explicitly
closed, and rejects attempts already carrying a terminal success, pre-start
cancellation, or post-start cancellation receipt.

The filesystem observer walks only the directory chain already journaled by the
publication protocol, using directory descriptors with `O_NOFOLLOW`. It reads
metadata for the private staging and final names without creating, removing,
renaming, linking, chmodding, writing, or hashing file contents. It records
whether the names are absent, match the pinned inode identity, form the expected
two-name hardlink state, or conflict with retained evidence.

The receipt includes the closed maintenance operation/generation, immutable
execution and publication evidence digests, and explicitly stores
`process_drain_verified=false`, `cleanup_authorized=false`,
`filesystem_mutation_performed=false`, and `full_host_closure=false`.
A valid observation remains a reconciliation blocker; it never settles or clears
an execution. The receipt is independent of business/raw-row deletion and is a
replay fence if those mutable rows are later removed.

Migration `20260919_0060` adds the non-cascading
`studio_crash_observations` ledger. It performs no backfill, accepts an existing
table only when frozen DDL matches exactly, and refuses destructive downgrade.

## Acceptance boundary

Tests must use disposable PostgreSQL and owned temporary files only. They cover
open-admission rejection, closed read-only observation, incomplete publication
layouts, idempotence, raw-row deletion/replay fencing, migration compatibility,
and source contracts forbidding filesystem mutation. Production deployment,
production migration, actual host drain, and cleanup after crash remain separate
FR-06 prerequisites.

## Observed local acceptance

- 9 focused disposable-PostgreSQL / real-filesystem crash-observation cases passed.
- The final extended Studio compatibility suite passed 417/417 cases after
  aligning the historical repeatable-read table expectation with the new ledger.
- Full backend Ruff passed and mypy passed on 288 application source files.
- A disposable PostgreSQL database completed the full Alembic chain through
  `20260919_0060`.
- The complete repository suite passed 1799/1799 tests on staged tree
  `8dc91d0395eb19f3db886ca9faa9524b5ce91dd1` before this acceptance note was
  appended. Because this note changes the tree, the repository suite is rerun on
  the final staged tree before commit; only that final result is used for commit
  acceptance.

The test labs were isolated from production and their registered containers and
networks were removed after use. These results are source acceptance only and do
not claim production migration, deployment, process drain, filesystem cleanup,
or full-host closure.
