# FR-06D8C4B6A — Studio crash containment provenance

Source-only, database-only provenance after the merged B5 staging quarantine. The stage binds the exact retained C4A crash observation and B3 cleanup candidate to the accepted B4 process-reference receipt and B5 staging-quarantine receipt under the same closed maintenance operation/generation and boot.

It adds the immutable `studio_crash_containments` ledger at migration `20260920_0061`. Recording locks the retained observation/execution/publication evidence, reconstructs the cleanup candidate from durable evidence, rejects any conflicting success/prestart/poststart terminal receipt, validates the exact B4/B5 chain and current closed maintenance authority, and is idempotent only for the exact same proof.

B6A performs no filesystem access or mutation, process/container control, admission opening/closing, retry, settlement, quarantine deletion, final deletion, or blocker clearing. A valid containment remains diagnostic only: `filesystem_cleanup_claimed=false`, `blocker_cleared=false`, `retry_authorized=false`, `process_drain_verified=false`, `cleanup_authorized=false`, `settlement_authorized=false`, and `full_host_closure=false`. Raw execution/publication/crash evidence is retained.

Snapshot integration exposes valid/invalid/orphan containment evidence but deliberately does not subtract containment rows from `blocker_count`. Raw-evidence drift converts the containment to invalid/reconciliation-required rather than crashing the whole snapshot or turning the attempt terminal.

Final local source acceptance on the B6A worktree: 17/17 isolated PostgreSQL integration cases passed; 8/8 root source-contract tests passed; the complete root repository suite passed 1928/1928. Migration `20260920_0061` upgraded a fresh disposable PostgreSQL database from base through head, produced `studio_crash_containments`, re-applied `upgrade head` idempotently, and the disposable database was removed. Ruff passed on all changed backend source/tests; mypy reported no issues in the new containment service and modified registry; Phase 36 reporting, py_compile, and diff checks passed.

Production migration/deployment has not been performed by this source stage.
