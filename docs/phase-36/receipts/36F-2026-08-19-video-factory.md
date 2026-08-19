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
