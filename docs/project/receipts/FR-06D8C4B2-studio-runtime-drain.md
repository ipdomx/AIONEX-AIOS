# FR-06D8C4B2 — Studio runtime drain

Dependent source increment on C4B1. It combines an immutable Studio writer-epoch receipt with a backup-cycle snapshot from the same closed maintenance operation/generation and rechecks the current Compose container epoch.

Acceptance requires the exact backend/studio-worker container identities and restart counters to remain unchanged, the backup worker identity to remain unchanged, the one-shot asset-root initializer to be absent, the Studio volume identity to remain exact, and backup active/unresolved/expired/unfinished counts all to be zero. The backup snapshot must postdate the writer-epoch receipt.

This is still not cleanup authority. The receipt keeps `process_drain_verified=false`, `host_process_scan_verified=false`, `cleanup_authorized=false`, `filesystem_mutation_performed=false`, and `full_host_closure=false`.

Local draft acceptance: 18 focused tests, Ruff success, and 1833/1833 complete repository tests on the dependent C4B1 source. The branch remains local until C4B1 is merged and accepted.
