# Phase 36C / FR09: truthful local Free project execution consent and attribution

**Date:** 2026-10-26. **Ledger:** P36-0091. **Scope:** source-only, no production deployment.

## Verified production mismatch
- Backend was armed on the existing production immutable image with only
  PROJECT_EXECUTION_RUNNER_MODE=phase36c and
  PROJECT_AI_LIVE_RUNTIME_ENABLED=true. 8 CPU, 8 app workers, original DB
  pool and image are retained. Four project AI workers stay healthy.
- The production Free policy is enabled, offline_only=true,
  privacy_mode=true, max_fallbacks=0, provider/model Ollama gemma3:4b, and
  maximum external provider charge USD 0. The operations observer refreshed
  its validated local-model evidence at 13:02 UTC.
- The durable POST project execution API previously treated *every*
  non-provider-neutral request as external processing: it demanded
  confirm_external_processing=true, persisted provider=openai and budget
  cap USD 0.05 even for a Free local-only project. These audit fields and
  consent semantics conflicted with the Owner's routing policy; they could
  incorrectly imply an external transfer or a billable project.
- The portal currently submits the generic confirmation field for full
  project modes. That input must not transform a Free-only local route into
  a false external-processing record.

## Source-only correction
- For active Free users on full/planning project execution, resolve the
  **effective** current Owner Project AI access policy before queueing or
  consuming user-message credits. Require an explicit Free class,
  offline_only, privacy_mode, exact Ollama provider allowlist, at least one
  Ollama model, zero external USD cost, and no fallback. Reject missing,
  disabled, external, billable, or unsafe overrides with redacted 503 errors.
- Do not invent external processing consent: local Free projects persist
  provider=ollama, external_processing_confirmed=false, USD 0 budget cap.
  Client-provided generic external-processing=true cannot override the
  actual server policy and cannot mark a local job external.
- Preserve existing paid/external and 3D modes: explicit external
  confirmation remains required before queueing; provider-neutral snapshots
  remain zero-cost/non-external with truthful "no AI invoked" receipt.
- Continue to use the existing durable worker to select the actual model
  from live validated provider evidence. No OAuth, database migration,
  billing action, queue replay, Owner approval, payment setting, or provider
  request was introduced by this source change.

## Test evidence
- 13/13 focused native unittest cases PASS in a network=none, read-only
  official backend container with only synthetic actor and pure mocks.
  Cases cover true local acceptance without external consent; false external
  claim even when client says true; paid and 3D consent preservation;
  unarmed runtime 503; no reachable policy; external or costly Owner user
  override denial; provider-neutral behavior; and accurate durable
  metadata tuple (provider, external consent, budget).
- 126/126 pure FR09 and Phase36 governance tests PASS in the local source
  worktree. No production database rows were created or modified.
- Protected GitHub CI and source review are still required before merge.
  No production deploy or FR25 G9 generation change from this PR.

## Remaining before full release
- A real authenticated end-to-end Free project sample with actual local
  model output is NOT yet accepted; the source-only unit tests do not
  prove the job completed or that its complete engineering/governance stack
  ran. Independent FR08 Owner recovery and rights, FR09 sustained 5000
  genuine concurrent users / 15000 durable model jobs, provider quotas,
  and a natural clean FR25 72-hour window remain HOLD.
- Production still runs the previous API file until a separate controlled
  Backend deployment. Rollback is revert of the source-only change; no
  current customer data can be rolled back from this branch.

**Full release verdict: HOLD.**
