# Phase 36N — Trivy build process lifecycle (source only)

Continuation within FR-06 from held PR #811 head `7d78a7fb0fc419962409c8f5bbe1da519b8e6f80`.

The detailed scope, reproduced failure, native process tests, complete Root acceptance, source hashes, unchanged runtime observation and limitations are in [the canonical source receipt](../../project/receipts/FR-06-trivy-owned-process-lifecycle.md).

Two native descendant late-write regressions failed before correction. After the correction, 3310 Root tests passed with no failures, errors or skips; 66 focused tests, including 16 new lifecycle cases, are included in that total. Ruff and Mypy passed. No scanner detector/rule, vulnerability exemption, module lock, compiler identity, expected executable fingerprint, shared runner, workflow or production configuration was changed.

The 40 existing containers retained their identities, images, start times and restart counts; 36 are running and none of those is unhealthy. The live source remains frozen. Stopped initialization health states are retained, not counted as running failures or falsely declared healthy.

No fresh image build or vulnerability scan is claimed. The prior image still has 200 HIGH/CRITICAL findings. Merge/deployment HOLD, FR-06, full-host closure, expanded capacity acceptance and final release remain open. No capability maturity is promoted by this source-only correction.
