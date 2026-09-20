# FR-06D8C4B4 — Studio candidate process-reference scan

Read-only exact-inode scan chained to C4B1/C4B2 receipts and a C4B3 cleanup candidate. It rechecks the writer epoch, read-only backup-reader identity/mount, and staging/final identity, scans each thread twice for fd/cwd/root/exe/mmap references, and remains non-mutating. Full process drain, cleanup authorization, final deletion, production deployment, and full-host closure remain false.

Canonical detail: docs/project/receipts/FR-06D8C4B4-studio-process-reference-scan.md
