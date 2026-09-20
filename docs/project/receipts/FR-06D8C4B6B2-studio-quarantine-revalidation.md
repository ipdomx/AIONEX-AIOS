# FR-06D8C4B6B2 — Studio quarantine host revalidation

Source-only, host-side, read-only revalidation after B6B1. This stage does not terminalize, settle, retry, clear blockers, delete quarantine/final names, mutate Studio bytes, change containers, change admission, or migrate/deploy Production.

The input is the exact B6B1 terminal candidate. B6B2 validates its self-digest and safety flags, then derives the **current** Studio volume source from fresh Docker inspection rather than trusting a historical source. It requires exactly one running `backend` and one running `studio-worker` with RW access plus one `backup-worker` with read-only access to the same Studio destination/source. Any unexpected service, alternate destination to the same source, malformed mount, or container epoch drift fails closed.

The exact relative path from B6B1 is reopened through `O_NOFOLLOW` directory descriptors. The original staging name must remain absent. The deterministic retained quarantine name must resolve to the exact B5 retained identity and the final-name layout must remain consistent, including the same inode when the final hardlink exists.

B6B1 now also carries the durable archive `size_bytes` and SHA-256 checksum from the validated `StudioPublication.plan`. B6B2 pins the quarantine with an `O_NOFOLLOW` file descriptor, verifies size, hashes the retained bytes twice around two complete candidate-specific `/proc` scans, and requires both hashes to equal the durable publication checksum. This closes the stat-only inode-reuse/same-size replacement gap.

Two fresh Docker inventories bracket the host revalidation and must match exactly for container ID, restart count, start time, RW mode, source, type, and name. The current boot ID is recorded separately from the historical containment boot ID. A different boot is allowed because the host proof is rebuilt from scratch rather than extending same-boot B4/B5 scan claims.

A successful receipt may claim `quarantine_reference_drain_verified=true`, `host_process_scan_verified=true`, `archive_content_revalidated=true`, and `current_container_epoch_stable=true`. It still keeps `process_drain_verified=false`, `authority_revalidation_required_by_next_stage=true`, `terminalization_authorized=false`, `blocker_cleared=false`, `retry_authorized=false`, `filesystem_cleanup_claimed=false`, `filesystem_mutation_performed=false`, `cleanup_authorized=false`, `settlement_authorized=false`, `quarantine_deletion_permitted=false`, `final_deletion_permitted=false`, and `full_host_closure=false`.

The optional CLI persists only the resulting receipt outside the Studio namespace in a pre-existing root-owned private state directory using create-only `O_EXCL|O_NOFOLLOW` mode 0600 semantics. Production execution has not been performed by this source stage.

Protected acceptance of B6B2 remains gated on protected merge/acceptance of B6B1 first.

Current stacked-draft acceptance: 18/18 focused functional+contract tests passed; the complete root repository suite passed 1953/1953. Ruff passed the new script/tests; Phase 36 reporting, py_compile, PLAN JSON validation, and git diff checks passed. No Production execution, deployment, database migration, blocker clearing, terminalization, retry, cleanup, or deletion was performed.
