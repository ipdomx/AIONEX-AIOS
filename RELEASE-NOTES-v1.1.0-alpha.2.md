# AIOS Enterprise v1.1.0-alpha.2 — Cognitive Core

This release introduces the first executable institutional governance layer.

## Added
- Cell Registry with ten independent default cognitive cells.
- Deliberation Engine with repeatable review rounds.
- Weighted Voting Engine with quorum and protected security/governance rejection.
- Conflict escalation and conditional approval states.
- Append-only JSONL Decision Ledger.
- Governed self-evolution policy: sandbox, evidence, rollback, and human approval.
- Kernel integration under `cognitive_governance`.
- Regression tests for ordinary, destructive, and self-update proposals.

## Safety
This release updates only these existing files:
- `VERSION`
- `pyproject.toml`
- `src/aios/kernel.py`

All other paths are newly added. No database file, user project, secret, or runtime state is included.
