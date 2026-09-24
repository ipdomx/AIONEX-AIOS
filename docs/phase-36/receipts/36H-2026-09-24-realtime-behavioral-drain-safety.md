# 36H — Realtime behavioral drain safety

FR-06C5D9B4A adds actual disposable-PostgreSQL acceptance for the source-only D9B4 gate. It reproduces and fixes stale authority/local state across provider reads, malformed inventory being treated as empty, and cross-organization ownership history suppressing a legacy blocker. The full scope, before/after evidence and test limitations are in `docs/project/receipts/FR-06C5D9B4A-realtime-behavioral-acceptance.md`.

The corrected 65-case behavioral suite uses simulated provider transport but real PostgreSQL and a real disposable child-process exit; it is not live-provider or host-crash certification. No production migration, provider mutation, admission transition in Production, retry, automatic settlement, adoption, rollout authorization, or full-host closure. `docs/project/PROJECT-REPORT.md` and its runtime journal remain the only current continuation state.
