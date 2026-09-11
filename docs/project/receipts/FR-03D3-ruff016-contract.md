# FR-03D3 — Ruff 0.16.6 explicit compatibility contract

Base: `3c250c1bf96d7496955250acbb216719a4e2bec5`.

The proposed Ruff upgrade from 0.2.0 to 0.16.6 was not applied with the new implicit defaults. A read-only probe showed that Ruff 0.16.6 would enable 2,033 findings under its newer defaults, including 1,392 FastAPI `B008` findings and 204 import-order findings, even though Ruff 0.2.0 currently passes the repository unchanged. Effective-settings comparison proved the old contract was the legacy default rule set `E4,E7,E9,F` with Python target 3.8.

The candidate therefore upgrades the Ruff engine to 0.16.6 while making the existing lint policy explicit in `web-dashboard/backend/ruff.toml`:
- `target-version = "py38"`
- `select = ["E4", "E7", "E9", "F"]`

This preserves the existing enforced static-quality boundary instead of silently broadening or weakening it because of tool-default drift.

Acceptance:
- Ruff 0.16.6 with repository config: `All checks passed!`
- Effective Ruff rule set matches the old E4/E7/E9/F families and target Py38.
- mypy 2.3.1: `Success: no issues found in 262 source files` on Python 3.11.
- Contract tests: 2/2 PASS.
- AIOS core suite: 964/964 PASS.

Protected GitHub checks remain mandatory before merge. No production runtime behavior is intentionally changed by the Ruff upgrade itself.
