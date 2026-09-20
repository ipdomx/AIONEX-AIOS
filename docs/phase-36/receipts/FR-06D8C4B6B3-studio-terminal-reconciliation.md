# FR-06D8C4B6B3 — Studio terminal crash reconciliation

Database-only immutable terminal crash reconciliation at migration `20260920_0062`. It consumes exact B6B1+B6B2 evidence, requires unchanged current closed Studio maintenance authority for a new record, clears only the exact execution+crash-observation blockers, and retains quarantine/raw evidence.

It never retries, claims normal-success settlement, cleans/deletes Studio bytes, deletes quarantine/final names, claims full process drain, or claims full-host closure.

Canonical detail: docs/project/receipts/FR-06D8C4B6B3-studio-terminal-reconciliation.md
