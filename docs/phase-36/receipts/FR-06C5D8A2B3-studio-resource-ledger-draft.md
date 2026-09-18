# FR-06C5D8A2B3 — Durable Studio execution/thread evidence

Canonical review: `docs/project/receipts/FR-06C5D8A2B3-studio-resource-ledger-draft.md`.

The original local proof defects have been corrected. Acceptance passed 57
PostgreSQL/resource-ledger cases and 18 join cases (75 combined), plus the wider
369-case compatibility run which includes those cases. Ruff passed and mypy
passed on 280 application files; isolated migration reached 0055. The original
failed runs and previously blocked operations remain documented separately.

This increment preserves durable ownership, original interruption causes and
unverified-resource blockers. It does not implement filesystem cleanup,
settlement, production deployment or full-host drain. Repository/CI acceptance,
merge, synchronization and registered QA cleanup belong to the append-only
Project Hub at `/opt/AIOS/docs/project/PROJECT-REPORT.md`.
