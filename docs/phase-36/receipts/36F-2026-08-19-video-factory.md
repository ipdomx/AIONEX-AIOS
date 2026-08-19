# Phase 36F — Video, cinema, motion graphics & advertising factory

Date: 2026-08-19
Status: **IN PROGRESS — Stage 1 governed VideoPlan/continuity foundation; no live video generation or provider spend yet**

## Baseline

- Phase 36E is closed. Protected activation evidence PR #445 merged to `main` as `5ed61571790056183950f73c0fc22dfc38e2fdb1`; Production remains healthy with authoritative `current_batch=36F`, `36E=complete`, `36F=in_progress`, image execution flags false and active Design/Media/Project queues zero.
- Phase 36D already provides the reusable durable creative Media DAG, S3/object-store authority, scene/timeline metadata, dependency-aware partial regeneration and FFmpeg 9 render/assembly worker. Phase 36F must build provider-generated video scenes on that fabric rather than create a second graph or transcoder.
- Existing Production Studio Video output was still planning-only: deterministic shot list, subtitles, provider prompt notes and `render.sh`, with `provider=None`, `model=None`, `external_requests=0`, `external_cost_usd=0`. The script explicitly required users/operators to replace shot placeholders with approved generated or filmed media. This is not evidence of real text/image/logo-to-video execution.

## Current provider truth reviewed before source changes

- OpenAI's current Videos API exposes asynchronous video jobs for `sora-2` / `sora-2-pro`, prompt-based creation with an optional governed image reference, 4/8/12-second create durations, governed portrait/landscape sizes, job retrieve/download/delete and remix. Stage 36F1 deliberately does **not** claim separate OpenAI edit/extend operations that are not present in the current create/remix API reference.
- Current Google video-generation documentation/model inventory exposes Gemini video generation through Gemini Omni Flash preview and Veo 3.1 preview families. Because static documentation/model visibility can be broader than credential-specific accepted request shapes, Stage 36F1 treats these as planning/inventory capabilities only; operation-specific `ready` state requires later bounded live evidence.
- Fireworks remains connected as an AI provider but is not promoted into the 36F video-generation launch matrix because no governed video-generation contract has been accepted for it in this checkpoint.
- Credential-specific **List Models only** evidence was captured without generation or spend. OpenAI returned `sora-2` and `sora-2-pro`; Gemini returned `gemini-omni-flash-preview`, `veo-3.1-fast-generate-preview`, `veo-3.1-generate-preview`, and `veo-3.1-lite-generate-preview`. Sanitized evidence is retained at `.deployment-backups/phase36f-stage1/video-provider-inventory.json`, SHA-256 `d84a61eee9362c593a76d76c8c880b01ade178cb1d8ab7100befe591b2ef51f0`; `generation_requests=0`, `provider_spend_usd=0.0`.

## Stage 1 implementation

- Added `src/aios/video_factory.py` as the provider-neutral 36F planning domain. It introduces immutable governed contracts for video provider capabilities, runtime evidence, video requests, scenes, compiled provider-scene requests and deterministic VideoPlan snapshots.
- The request contract covers text/image/logo/reference-to-video plus edit/extend/remix semantics only where a provider matrix explicitly declares them. Reference ownership is fail-closed: text-to-video accepts no reference; image/logo/edit/extend/remix require exactly one governed reference; reference-to-video accepts one to three governed references.
- The launch matrix is deliberately conservative. Sora 2/Pro use only the exact current create/reference/remix contract and governed 720p launch sizes; Veo/Omni entries remain planning candidates and cannot become live-ready from model inventory alone. `runtime_ready_provider()` requires explicit operation-specific `VideoRuntimeEvidence(state="ready")`; `inventory_visible` is insufficient.
- Default advertisement/cinematic planning produces four deterministic scenes (`opening`, `value`, `proof`, `close`) with stable durations, purpose, transition, optional narration/reference role and a checksum-derived continuity ID. Every compiled scene prompt carries the same continuity ID and explicit identity/product/wardrobe/lighting/spatial-continuity guidance.
- `VideoPlan.public_snapshot()` is schema `36F.video-plan.v1`, remains `render_status=planned`, includes no credentials/API keys/signed URLs and never represents static capability or a provider prompt as rendered video.
- Production Studio Video now derives its shot list and provider prompt pack from the governed VideoPlan and adds `production/video-plan.json` plus `production/continuity-manifest.json` (`36F.continuity.v1`). Subtitles are generated against governed scene durations. The retained FFmpeg handoff is explicitly marked `PLANNED ONLY`; it may consume only completed governed provider/filmed scene nodes in a later stage.
- Studio archive truth is unchanged until durable execution exists: provider mode remains neutral, provider/model remain `None`, external request count remains `0`, external cost remains `$0`. Adding VideoPlan metadata therefore cannot be mistaken for a completed provider video.

## Verification

- Phase 36F VideoFactory: `7/7 PASS`.
- Production Studio + affected Phase 36D Media Orchestrator regression: `16/16 PASS`.
- Regression explicitly proves Studio video archives still have `provider=None`, `model=None`, `external_requests=0`, `external_cost_usd=0` and planned video/continuity manifests.
- Ruff: PASS.
- Focused Mypy: PASS.
- Python compile: PASS.
- `git diff --check`: PASS.
- No database schema/data mutation, provider video-generation request, video-provider spend, Production S3 write, service restart or worker activation was performed by Stage 36F1.

## Remaining before 36F can close

1. **Stage 36F2 — durable asynchronous video execution authority.** Add a dedicated video execution record/worker rather than overloading `DesignImageExecution`; explicit arm-before-spend, idempotency, provider job ID/state, polling, retry/fencing, usage/cost, governed input references, download/checksum/S3 completion and cleanup. Reuse the existing Media DAG provider-source scene nodes.
2. Implement exact provider adapters against the accepted live launch paths (initially OpenAI Sora and selected Gemini/Veo paths) with sanitized provider errors and operation-specific capability truth. Model inventory alone must never make a provider route ready.
3. Connect completed provider clips to the existing Phase 36D scene graph, subtitles/narration/audio inputs and FFmpeg final assembly. Preserve one Studio asset/revision authority rather than introducing a parallel video asset store.
4. Add motion/compositing contracts: transitions, kinetic typography, overlays/effect graph, captions/subtitles, narration/music/sound and ad/explainer/product/social/cinematic schemas.
5. Expand governed exports beyond the existing H.264 MP4 / AV1 WebM baseline: MOV and H.265/ProRes only when shipped FFmpeg codec/legal/runtime evidence is explicit; add 1080p/1440p/4K profiles without claiming unsupported provider source resolution.
6. Run bounded live provider acceptance one operation/model at a time with cost caps, complete DB/S3 cleanup and persistent workers disabled by default. Do not infer readiness from successful List Models.
7. Prove the authoritative 36F exit gate in Production: a logo + brief must create a **real multi-scene advertisement**, not a storyboard; a long-form graph must survive worker failure and resume/re-render only failed/affected scenes before final FFmpeg assembly.
8. Only after protected CI, backup/restore for any schema change, deployment, provider canaries, final output QA, cleanup and post-health may 36F become `complete` and 36G become current.

## Safe point

Stage 36F1 is source/test-only. Production remains on the accepted Phase 36E-closeout runtime with 36F current but no unattended video-provider execution. The next safe implementation boundary is the dedicated durable asynchronous VideoExecution authority; no live generation should be attempted before that authority is protected by tests and CI.

## Checkpoint 1B — Protected Stage 1 merge and Production planning activation

- Protected PR #446 (`Phase 36F Stage 1 governed video planning foundation`) passed every required gate: Backend Tests `6m07s`, Production Docker Build `17m42s`, Owner/VIP Browser boundaries, CodeQL Python + JavaScript/TypeScript, Backend SBOM/vulnerability, Frontend Build, Core contracts, Dependency Security, repository secret/hygiene and Phase36 Reporting. PR #446 merged into `main` as `6792872f5abb41432e39d7435b8baa15607862cf`.
- Pre-deploy Production truth was clean: Backend/Media/Image/Derivative services Healthy, active Design/Media/Project queues `0/0/0`, persistent Design Image and Derivative execution flags false. The pre-deploy Backend image `sha256:45577b26ef1aecb79728d79277f51e2573af4e48b5e4fd290989673e53fe7119` was retained as a Stage 36F1 rollback tag.
- Production source fast-forwarded from `main@5ed6157` to merged `main@6792872`. No schema migration was required for Stage 1. Backend alone was rebuilt/recreated; Media/Image/Derivative workers were deliberately not restarted.
- Pre-recreate and post-recreate smoke both proved the exact planning boundary: Video Studio emits schema `36F.video-plan.v1`, four scenes plus continuity metadata, planning model Sora 2, `render_status=planned`, `provider=None`, `external_requests=0`, `external_cost_usd=0`. The running Backend became Healthy with direct `/ready` HTTP 200 and authoritative `current_batch=36F`.
- Post-deploy worker health remained green, persistent image flags remained false and active queues remained `0/0/0`. Sanitized Stage 1 deployment evidence is retained at `.deployment-backups/phase36f-stage1/phase36f-stage1-production.json`, SHA-256 `8d273b2346be71a964bea2e26b7f1382334a91de43a7ec8d60b019c54658713d`. No video provider generation request or spend occurred during deployment.

## Checkpoint 2A — Durable asynchronous VideoExecution authority (source/test candidate)

- Added Alembic `20260819_0034` and a dedicated `video_executions` authority rather than overloading `DesignImageExecution`. Each execution is tenant/project/Studio/Media-DAG scoped to one provider scene node and starts `planned`; only explicit `arm_video_execution()` can make it claimable.
- The durable record separates **provider submission attempts** from **provider polling/reconciliation observations**. A fresh claim is `mode=submit` and consumes `attempts`; the worker must durably call `mark_submission_started()` **before provider HTTP**. If that worker crashes after the provider may have accepted the request but before a job ID is stored, the reclaimed claim becomes `mode=reconcile` instead of `mode=submit`, consumes only the bounded observation budget and cannot silently submit a second paid job. After `provider_job_id` is durably recorded, later claims are `mode=poll` and also consume only `poll_count`.
- Provider job identity is immutable after persistence and `(provider, provider_job_id)` is unique. `record_provider_job()` is accepted only from `submit/reconcile` claims, pending/completion updates only from `poll`, and a definitive submission failure may reopen submit budget only through an explicit `submission_safe_to_retry=True` path. Lease ownership, expiry and fencing reject stale workers after reclaim. Bounded submission/reconciliation/poll exhaustion dead-letters the execution instead of looping indefinitely.
- Provider scene nodes intentionally carry no FFmpeg operation, so no MediaRenderStep is created for them. The existing downstream assembly step remains `planned` and the Phase36D FFmpeg worker cannot claim it until all parent provider-scene nodes are `completed`; the existing Media DAG therefore remains the single video dependency/resume authority.
- Completion is fail-closed: current raw provider-scene output is MP4-only; a basic MP4 envelope and governed `video/mp4` content type must pass before object-store write. Storage occurs through the existing MediaObjectStore and final DB completion is fenced; failure after storage deletes the just-written object. Provider output sets the scene node to completed but leaves the graph `rendering` while assembly remains pending. Final FFmpeg/ffprobe QA remains a Stage 2B worker responsibility rather than being falsely claimed by the DB authority.
- Public graph snapshots continue to omit prompts, physical storage keys and private provider job IDs. Provider response/usage metadata is bounded and strips credentials, auth/token fields, prompts/base64 and signed/download URLs before persistence. Actual cost remains nullable when unknown and carries an explicit cost basis.
- Migration verification on disposable PostgreSQL 16: fresh upgrade to `0034` PASS; `0034 -> 0033 -> 0034` recovery PASS. Initial Video/Alembic gate `10 PASS`; after submission-ambiguity hardening the final combined Video + Phase36D Media + retained DesignImage/fencing + Alembic regression is `20/20 PASS`, including `max_attempts=1` crash recovery into reconcile mode without a second submit attempt. Ruff PASS; focused Mypy PASS; Python compile and `git diff --check` PASS. Disposable PostgreSQL/Redis/network resources were removed.
- Stage 2A contains **no provider HTTP adapter, no provider video call/spend, no Production DB migration and no worker activation**. The authority now represents ambiguous submission durably instead of resubmitting. Stage 2B must implement provider-specific reconciliation for `mode=reconcile`: use a documented idempotency/request identity when available, or reconcile against provider-visible recent jobs with a unique request fingerprint when safely possible; if no unique provider job can be proven, fail closed for operator/user review rather than spending again.

### Next safe gate

Protect and merge Stage 2A, then deploy Alembic `0034` with a fresh Production backup/restore and keep video execution unarmed. Only after the durable authority is deployed should Stage 2B add exact Sora/Gemini adapters, a live-disabled Video Provider Worker, governed VideoPlan -> Media DAG pipeline creation and image/logo/reference inputs. Before any paid live canary, prove the provider-specific implementation of `reconcile` plus exact MP4/FFprobe QA; inventory/model visibility alone remains insufficient.
