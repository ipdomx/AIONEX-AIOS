# Phase 36N receipt — FR-03D2 remove unused isort

Scope: dependency/toolchain cleanup only.

isort 9.0.1 was evaluated read-only and would produce 8,846 lines of import-format churn under its defaults. The repository does not invoke isort from CI, pre-commit, scripts, or backend automation, so the unused isort 5.13.0 development pin is removed instead of performing a mass format migration.

Acceptance: Python 3.11 requirements install with no isort present; Ruff PASS; mypy 2.3.1 PASS across 262 source files; dependency/automation contract 2/2 PASS; AIOS core 962/962 PASS. No deployment occurs in this receipt.
