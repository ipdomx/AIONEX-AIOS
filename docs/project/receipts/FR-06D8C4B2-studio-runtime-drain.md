# FR-06D8C4B2 — Studio runtime drain

Dependent source increment on C4B1. It combines an immutable Studio writer-epoch receipt with a backup-cycle snapshot from the same closed maintenance operation/generation and rechecks the current Compose container epoch.

Acceptance requires the exact backend/studio-worker container identities and restart counters to remain unchanged, the backup worker identity to remain unchanged, the one-shot asset-root initializer to be absent, the Studio volume identity to remain exact, and backup active/unresolved/expired/unfinished counts all to be zero. The backup snapshot must postdate the writer-epoch receipt.

This is still not cleanup authority. The receipt keeps `process_drain_verified=false`, `host_process_scan_verified=false`, `cleanup_authorized=false`, `filesystem_mutation_performed=false`, and `full_host_closure=false`.

Final local acceptance before PR: 31 focused/runtime/exporter tests, Ruff success, mypy success across 289 application source files, Project Hub and Phase-36 reporting validation, and 1842/1842 complete repository tests on final staged tree `c3897f684914d8d6da5e866d90dca126d65fc996`. C4B1 and its merged-main checks were accepted before opening this dependent PR.


Operational input path: C4B2 also ships a read-only snapshot exporter. The backend exporter sandwiches Studio and backup observations between closed-admission reads and refuses output if the maintenance authority changes. The host wrapper selects exactly one backend container and writes create-only `admission.json`, `studio.json`, and `backup.json` files with mode 0600. It performs no container control, admission transition, database mutation, or Studio filesystem mutation.
