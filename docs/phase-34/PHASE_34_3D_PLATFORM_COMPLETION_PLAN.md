# Phase 34 — Complete 3D Platform Productionization

Goal: finish the AIONEX AIOS 3D generation platform end-to-end with no known gaps between serverless generation, production operations, product integration, optimization, observability, billing, licensing/region controls, and release acceptance.

## Delivery batches

### 34A — Repository hygiene and pending change closure
- Merge Stripe restricted-key readiness support and its regression test in an isolated change.
- Restore historical tracked ZIP artifacts locally so unrelated deletions disappear from the working tree.
- Ignore runtime-only local directories and artifacts: deployment backups, audit virtualenv, data, releases, local tool clones/logs/caches.
- Extract only reproducible RunPod/Hunyuan runtime source into tracked `infra/runpod/hunyuan3d/`; do not commit model weights, generated GLBs, secrets, logs, or cloned third-party repositories.
- Record the exact known-good RunPod image tag and digest and the final template requirements.
- Validate Phase 33 tests, billing regression test in the correct backend environment, then the complete root suite.

### 34B — RunPod production endpoint and scale-to-zero acceptance
- Create a dedicated production endpoint from the known-good template/image.
- Keep min workers 0, max workers 1, no active workers, bounded execution timeout, bounded init timeout, and no command override.
- Persist only the endpoint ID in the protected production secret file.
- Prove image-to-GLB live generation.
- Prove automatic scale-to-zero without deleting the endpoint.
- Add queue purge, cancellation, timeout, retry, and stuck-job recovery acceptance tests.
- Add explicit cost guardrails and owner alerts.
- Restrict 3D service access by default to the highest current plan (`business`) plus the `3d.generation` entitlement; all plan/user overrides, limits, and enable/disable controls are Super Owner-managed through `/owner/3d`.
- Keep Phase 34 work isolated from unrelated parallel conversation/worktree changes; merge only files owned by the active batch.

### 34C — Full textured/PBR 3D pipeline — COMPLETE
- Move from shape-only GLB acceptance to full texture/PBR generation.
- Run Blender post-processing.
- Run glTF Transform optimization and validation.
- Add mesh cleanup, material/texture validation, compression policy, and deterministic artifact checks.
- Measure generation duration and before/after artifact size.
- Preserve graceful fallback to shape-only only when policy explicitly allows it.
- Acceptance evidence: `docs/phase-34/PHASE_34C_PBR_ACCEPTANCE.md`; two same-seed live GPU runs produced the same validated non-fallback PBR GLB SHA-256 and the production endpoint scaled to zero.

### 34D — Product integration in AIOS and ai.vip-e.net
- Expose authenticated project API for create/status/cancel/download.
- Connect project/workspace ownership and organization isolation.
- Persist job/audit state and artifact metadata.
- Store final artifacts in protected object storage and return expiring download/view URLs.
- Add Three.js preview and user-visible progress/error states.
- Enforce plan quota, concurrency, timeout, and billing/metering.
- Emit owner and user notifications for clarification, progress, completion, cancellation, and failures.

### 34E — Security, observability, cost, and resilience
- Structured logs, metrics, tracing, health, job duration, cold-start, GPU runtime, success/failure rate.
- Circuit breaker and provider outage handling.
- Idempotency and duplicate-job protection.
- Cleanup policy for temporary files and stale artifacts.
- Daily/monthly spend ceilings, per-user limits, and owner alerts.
- Image vulnerability scan/SBOM and dependency pinning.
- Disaster recovery and rollback procedure.

### 34F — License, region, and provider-policy gate
- Document exact Hunyuan3D license obligations against the pinned version.
- Enforce region availability policy where required.
- Add disclosure/terms text required for third-party model service use.
- Provide a configured fallback provider/model path for excluded regions or policy failures.
- Prevent routing to an unavailable/non-permitted provider.

### 34G — Production release and final acceptance
- Deploy the merged main revision to production.
- Verify production services and current commit.
- Run full domain-level E2E: upload image -> job -> GPU -> textured optimized GLB -> storage -> preview/download -> notifications -> metering.
- Run failure/cancel/timeout/quota/provider-outage E2E cases.
- Confirm scale-to-zero and no idle GPU spend.
- Confirm rollback.
- Archive a signed release receipt, test evidence, image digest, and final readiness report.

## Definition of complete
Phase 34 is complete only when every batch above has passed its acceptance checks, no runtime-only artifact or secret is committed, all CI checks are green, production E2E passes, and there is no known unresolved functional/security/cost/licensing/release item in this plan.
