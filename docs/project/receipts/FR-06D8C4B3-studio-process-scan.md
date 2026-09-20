# FR-06D8C4B3 — Studio process-reference scan

This source-only increment proves a bounded host-visible reference condition for the current Studio asset volume. It consumes accepted C4B1 writer-epoch and C4B2 runtime/backup-drain receipts, rechecks the exact running writer/reader container epoch, inventories the current Studio volume without following symlinks, and performs two /proc scans for references to the current volume objects.

The scan covers file descriptors, cwd, root, exe, and mmap references visible through /proc, including per-thread descriptors and map_files. The filesystem inventory must remain metadata-stable before, between, and after both scans; symlinks, special entries, nested filesystems, ambiguous/disappearing process references, changed writer/reader container epochs, changed volume identity, or any visible holder block the receipt.

A successful source receipt may state host_visible_studio_reference_scan_verified=true and studio_process_drain_verified=true, but deliberately retains process_drain_verified=false, cleanup_authorized=false, filesystem_mutation_performed=false, and full_host_closure=false. This prevents a Studio-scoped /proc observation from becoming a claim about every host process, kernel reference, or other FR-06 resource.

The source performs no kill/stop/restart, no admission or database mutation, and no Studio file deletion/rename/chmod/write.

Local pre-integration acceptance: 20 focused tests and Ruff passed. The complete repository suite passed 1853/1853 on an isolated copy before rebasing this increment onto the final accepted PR #737 merge; final-tree acceptance is rerun after that base is available.
