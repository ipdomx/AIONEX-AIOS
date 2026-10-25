# FR09 — AI-only project integration must not grant full project approval

Date: 2026-10-25 UTC. Project: AIONEX AIOS (`/opt/AIOS`).

## Previously reachable unsafe state

`DeterministicProjectAIIntegrationRunner` returned `"approved": true` and `"readiness_score": 1.0` in the same output as `"integration_foundation": true` and `"all_governance_layers_executed": false`. Its consumer `ProjectExecutionWorker.complete` used that approval flag to mark the durable job and associated project as approved, and to notify users that the full governed cycle had succeeded. Real model output alone does not establish Owner, human, workforce, security and final-release governance.

## Narrow fail-closed source correction

- An AI-only integration result now emits **`approved=false`, `readiness_score=0.0`**, while preserving its actual model provider, token counts, project-memory and durable route accounting.
- Independently, **`ProjectExecutionWorker.complete`** normalizes any result whose `integration_foundation` is **exactly true** but `all_governance_layers_executed` is not **exactly true**, overriding misleading approval and score fields before persistence. It sets `release_approval_withheld=true` and `release_approval_withheld_reason=governance_incomplete`.
- Ordinary `ProjectPlanningRunner` governed completions are **not changed** by this integration-only guard. A truly fully governed future integration still requires its own independent admission.
- The durable job can remain `completed` as an **AI-routing work result**, but its terminal stage must be `rework_required`, the project must not become finally approved, and the completion notification must not falsely certify full governance.

## Confirmed tests

- **16/16** fail-closed unit cases with falsified approval, scores, flags, or missing governance evidence.
- **17/17** disposable PostgreSQL 16 + Redis integration tests, including **100 tenant projects and six actual durable worker processes in one bounded synthetic acceptance test**. The 100 route outputs remained recorded, but all ungoverned final-approval states were withheld.
- Ruff and mypy succeeded on the two modified service modules and test.
- **4/4 real Ollama gemma3:4b invocations** through the **actual `ProjectAILiveProviderInvoker`**, real `DurableProjectAIRouteStore`, shared Redis coordinator, actual `ProjectExecutionWorker`, PostgreSQL 16 and actual project memory, inside an independent isolated Docker engine. Four tenant owners and four distinct projects; 96 input tokens, 12 generated output tokens, 4 durable routing attempts, 4 memories and 8 correlated claim/completion audit events.
- **All four real-model-backed jobs completed yet correctly remained `rework_required`, `approved=false` and `readiness_score=0`.** This corrected pilot intentionally injected an explicit synthetic provider policy rather than claiming full Owner policy governance.

Original bounded corrected model route proof SHA-256:
`f5ab71f72a485d9bc53bdff5514cbcfeaa30b9eba54198b4f0677a2199938f5b`

Original isolated orchestration manifest SHA-256:
`a916db8e1cdfefcf5b7c5177a338cedb854baff1dd71f2731d71a5fea826c521`

## Strict release boundary

This fix does **not** launch any new live workloads. No customer data, paid provider account, production DB table or container was changed. Four genuine routed model calls are a small successful **functional integration pilot**; not a 15,000-real-inference workload, not 5,000 simultaneous active users at the required all-route P95, and not 72 natural hours of post-deploy stability.

**Release decision remains HOLD.** Merge source only when protected CI is green. A source merge is not production deployment.
