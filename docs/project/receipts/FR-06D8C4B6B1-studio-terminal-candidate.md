# FR-06D8C4B6B1 — Studio crash terminal candidate

This source stage is a database-only, read-only export after accepted B6A crash-containment provenance. It does not terminalize, settle, retry, delete, clean, deploy, or migrate anything.

The exporter consumes one valid retained `studio_crash_containments` row plus the matching raw crash observation, execution, and publication evidence. It revalidates the B6A containment proof, rejects any conflicting normal-success, prestart-cancellation, or poststart-cancellation receipt, and requires the current Studio maintenance authority to be explicitly closed.

The original containment maintenance operation/generation and boot remain separate immutable evidence. A later closed maintenance operation/generation is permitted for reconciliation so an old crash does not become permanently unrecoverable after an authority rollover. The current reconciliation authority is embedded and digested into the exported candidate.

The candidate is deterministic while the same containment and current authority remain unchanged. It carries the retained quarantine name/inode identity, the B3 relative path plan, original staging name, final name/final evidence, and the original archive size plus SHA-256 checksum from the validated durable StudioPublication.plan, along with the exact B3/B4/B5 digests already bound by B6A. Those fields let a later host stage reopen the exact directory without guessing. It still explicitly requires host/quarantine revalidation before any terminal decision.

The output always keeps `terminalization_authorized=false`, `blocker_cleared=false`, `retry_authorized=false`, `filesystem_cleanup_claimed=false`, `cleanup_authorized=false`, `settlement_authorized=false`, `quarantine_deletion_permitted=false`, `final_deletion_permitted=false`, and `full_host_closure=false`.

B6B1 introduces no database migration and performs no database mutation. PR #742 / B6A merged as `badf231e37597826dcd45643fd63aa557e0464a2`, and all five post-merge main workflows completed successfully before B6B1 publication.

Final pre-PR acceptance on the rebased B6B1 branch: 8/8 isolated PostgreSQL integration cases passed against the post-merge base; 7/7 root source-contract cases passed; the complete root repository suite passed 1935/1935. Ruff passed the new service/test, Mypy reported no issues in the new service, and Phase 36 reporting, py_compile, JSON, and diff checks passed. The disposable PostgreSQL QA container/network was removed. Production remained unchanged at 36 running / 35 healthy / 0 unhealthy.
