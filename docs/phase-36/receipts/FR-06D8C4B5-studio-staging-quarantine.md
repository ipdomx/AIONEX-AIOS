# FR-06D8C4B5 — Studio retained staging quarantine

Source-only bounded containment after B4. The owned staging name may be atomically detached to a deterministic retained quarantine name using Linux renameat2(RENAME_NOREPLACE) only after chained B1/B2/B3/B4 evidence, exact inode/final-layout revalidation, four fresh Docker inventory checks on the mutation path (three on same-boot recovery, where no new rename occurs), and two pre- plus two post-rename candidate-specific /proc scans on the mutation path.

The same inode and any owned final hardlink are retained. Root execution and the pre-existing private receipt state-root are required before any namespace mutation. Crash recovery is same-boot and exact-inode only. No unlink, overwrite, byte deletion, settlement, cleanup authorization, process/full-host drain, deployment, migration, or production mutation is accepted here.

Canonical detail: docs/project/receipts/FR-06D8C4B5-studio-staging-quarantine.md
