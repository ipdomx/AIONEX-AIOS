# Phase 36E — Image, design, branding, infographic & prompt factory

Date: 2026-08-18
Status: **IN PROGRESS — provider worker source checkpoint; live acceptance pending**

## Baseline

- Phase 36D is closed and Production reports `current_batch=36E`.
- Existing Production Studio already exposes Image and Branding departments, but the Image department historically emitted a deterministic editable SVG plus a prompt-pack. That output is a useful editable planning/template artifact, **not** proof of provider-rendered image generation.
- Existing root `OpenAIProvider.image()` was still defaulted to `gpt-image-1` and had only a raw-transport contract; there was no unified durable production image execution fabric across OpenAI, Gemini and Fireworks.
- Phase 36D Media DAG/S3/Studio revision infrastructure is retained as the downstream asset/provenance authority. 36E must integrate with it rather than create a second asset store.

## Latest-provider / latest-library review

- OpenAI Platform currently presents **GPT Image 2** as the current image-generation path. Live authenticated model inventory for the existing OpenAI provider account returned `gpt-image-2`, snapshot `gpt-image-2-2026-04-21`, plus older GPT Image models. Foundation default is therefore moved from `gpt-image-1` to `gpt-image-2`.
- Google has shut down/deprecated Imagen 4 for this date and recommends the Nano Banana family. Live authenticated Gemini model inventory on the existing account returned `gemini-3.1-flash-image`, `gemini-3.1-flash-lite-image` and `gemini-3-pro-image`; these are the 36E Google launch models. No new 36E code targets Imagen.
- Existing Fireworks provider row is connected. Fireworks' current Image API is a workflow API separate from the OpenAI-compatible text model inventory. The launch matrix records `flux-1-schnell-fp8` for fast text-to-image plus `flux-kontext-pro` / `flux-kontext-max` for generate/edit workflows; the live adapter remains a later checkpoint.
- `sharp==0.35.3` is already pinned in both web frontends and is the current upstream release; it is retained rather than changed unnecessarily. Raster/export execution will be integrated only after the provider execution boundary is protected.
- Recraft and Stability remain optional expansion providers, not Phase36E launch dependencies, because the current Production provider registry/settings do not contain their governed credential entries.

## Foundation implementation

- Added `src/aios/design_factory.py` as a provider-neutral governed design domain:
  - immutable `BrandKit`, `DesignRequest`, `DesignPreset`, `DesignPlan` and `CompiledDesignPrompt` contracts;
  - responsive/export presets for logo, social square/portrait/story, advertising landscape, HD presentation, product, poster and infographic layouts;
  - launch image capability matrix for OpenAI GPT Image 2, Gemini 3.1 Flash/Flash Lite/3 Pro Image, Fireworks FLUX Kontext/Schnell;
  - deterministic provider ranking based on declared quality/latency/cost attributes while failing closed when a request requires unsupported transparency/reference/edit capability;
  - provider-specific prompt compilation, brand palette/typography/audience/exact-copy constraints and governed negative constraints;
  - deterministic plan checksum and public snapshot that does not contain provider credentials.
- Editable SVG output is explicitly marked `data-aionex-status="template"`; plan state is `planned`. The contract intentionally prevents a template or prompt pack from being represented as a rendered/final asset.
- Production Studio Image artifacts keep compatibility key `visual.svg`, but now also include `design-plan.json`, multi-provider `prompt-pack.md` and `export-presets.json`. The SVG is now a governed editable template tied to the plan checksum.
- Root OpenAI image adapter default changed from `gpt-image-1` to `gpt-image-2`. This is a contract/default update only; live image HTTP execution is not claimed by this checkpoint.

## Verification

- Phase36E Design Factory tests: `7/7 PASS`.
- Retained Production Studio tests: `9/9 PASS`.
- Ruff: PASS.
- Mypy on the new/modified source services: PASS.
- Python compile: PASS.
- No provider image generation request, image edit request, provider spend, Production database change, service restart or user asset mutation occurred in this checkpoint.

## Remaining before 36E can close

1. Implement hardened live image provider adapters for OpenAI GPT Image 2, Gemini 3.1 image models and Fireworks Image API with exact capability/error/usage mapping.
2. Add durable generation/edit/retry/fencing/idempotency records and route them through existing tenant/project/Studio boundaries.
3. Implement actual generation, edit/variation/inpaint/background operations only where the selected provider/runtime truthfully supports them.
4. Integrate real generated raster/source nodes into the Phase36D Media DAG/S3 authority and materialize Studio revisions with checksum/provenance/evidence.
5. Add brand-kit/template persistence and editable SVG composition backed by real generated imagery, not placeholder imagery.
6. Add governed raster exports and responsive/ad-size derivatives; retain `sharp 0.35.3` unless a later official release is verified before this gate.
7. Prove logos/branding, poster/ad/product mockup, infographic/diagram and experimental graphics through real outputs and revisions.
8. Run protected CI, backup/restore if schema changes, controlled live provider acceptance, Production canary, cleanup and post-health.
9. Only after the complete exit gate may 36E become `complete` and 36F become current.

## Safe point

Checkpoint 1 is source/test-only. Phase36E remains `in_progress`; no maturity is raised solely by planning/template code. Production remains on the already-accepted Phase36D runtime and Media Worker.

## Checkpoint 2A — Durable image execution authority (no live provider spend)

- Foundation PR #430 merged to `main` as `e46644aeea6cfec44f8b74123c6d4be2473bd677` after every protected gate passed.
- Added Alembic `20260818_0032` and durable `DesignImageExecution` authority bound to the existing Phase36D Media DAG / Studio / S3 model rather than creating a second asset store.
- Execution creation is fail-closed: new rows start `planned`; only an explicit `arm_design_image_execution()` transition may make them claimable. Creating a user design request alone cannot trigger provider spend.
- Provider/model/operation is validated against the Phase36E launch matrix from `src/aios/design_factory.py`; arbitrary provider/model strings are rejected.
- Provider-image nodes intentionally omit FFmpeg `operation`, so Phase36D Media Worker creates no `MediaRenderStep` and cannot claim image-provider work.
- Durable execution supports tenant-scoped idempotency, parent-node dependency gating, lease renewal, reclaim/fencing, retries, provider request IDs, bounded usage/cost evidence, output checksum/storage metadata and AuditEvent evidence.
- Provider responses are sanitized before persistence: prompt/base64/token/credential/signed-URL style fields are removed from evidence. Raw provider output must pass a fail-closed PNG/JPEG/WebP envelope+dimension validator before it can be stored or materialized as final.
- Storage writes/deletes are moved off the async event loop. Successful completion writes the existing `MediaAssetNode`, completes a one-node graph when ready, and materializes a real `StudioAssetRevision` with checksum/provider/model/cost evidence.
- Fresh PostgreSQL 16 install reached Alembic `0032`; focused authority tests `5/5 PASS`. Migration recovery `0032 -> 0031 -> 0032` PASS and the table was proven absent/present across the round-trip. Disposable databases were removed afterward. Ruff/Mypy/compile PASS.
- No OpenAI/Gemini/Fireworks image generation/edit request, provider spend, Production schema mutation, Production service restart or user asset mutation occurred in checkpoint 2A.

### Next safe gate

Checkpoint 2B adds the actual HTTP provider adapters + image worker behind the explicit arm boundary, with fake-provider/error mapping tests first. Only after those pass may bounded live provider acceptance be attempted.


## Checkpoint 2B — HTTP provider adapters and fail-closed image worker (no live provider spend)

- Added provider-specific HTTP adapters for the current launch pool: OpenAI GPT Image 2 generation/edit, Gemini 3.1 Interactions image generation/edit, Fireworks FLUX Schnell synchronous generation and FLUX Kontext asynchronous create/poll workflows.
- Adapter tests use `httpx.MockTransport` only. Protected request-shape/error-mapping verification covers OpenAI generate/edit, Gemini inline image references, Fireworks Schnell binary output, Fireworks Kontext bounded polling, and sanitized 401/402/429/5xx mappings. No provider endpoint is contacted by these tests.
- Added `DesignImageWorker` behind `DESIGN_IMAGE_LIVE_ENABLED=false` by default. When disabled, it never claims a durable image execution. The worker resolves exactly one connected/enabled provider from the existing Platform Provider Organization, obtains credentials only through the established encrypted/environment provider authority, and validates the official provider base URL boundary.
- Reference/mask inputs come only from completed parent nodes in the existing Media DAG and are read through the governed MediaObjectStore. User-supplied arbitrary remote URLs are not used as execution inputs.
- Worker retry behavior is evidence-based: rate-limit/transport/service failures remain retryable; authentication, billing, policy/input and unsupported-provider failures are permanent so the durable authority does not retry unsafe/non-recoverable requests.
- Production Compose now defines a separate `image-execution` profile for `design-image-worker`, running non-root as `1000:1000`, with `cap_drop: ALL`, `no-new-privileges`, inherited governed storage, and `DESIGN_IMAGE_LIVE_ENABLED=false`. Merely deploying the source cannot arm provider image spend.
- End-to-end source acceptance on disposable PostgreSQL 16 at Alembic `0032` uses the real durable authority + real worker + real platform-provider lookup + LocalMediaObjectStore + a Fake Provider Adapter. The full 2A/2B focused suite is **22/22 PASS** and proves planned→arm→claim→provider-result→raster validation→Media node→Studio revision, plus fencing/retry and public evidence boundaries.
- 2B remains source/test-only. Actual provider pricing/accounting validation, live OpenAI/Gemini/Fireworks requests, Production migration/worker activation and user-facing provider generation remain blocked for the next controlled live-acceptance checkpoint.

## Checkpoint 3A — Truthful image cost accounting before live acceptance

- Production infrastructure is already staged safely from merged PR #432: Alembic `20260818_0032`, Backend and one non-root Design Image Worker are healthy, real inherited S3 preflight passes, and the worker remains `DESIGN_IMAGE_LIVE_ENABLED=false` with zero image rows/active work. No live provider image call has occurred.
- Live acceptance was deliberately blocked before the first paid image request because `ProviderImageResult.actual_cost_usd` previously defaulted to `0.0`, which could falsely represent a paid provider call as free when a provider response omitted directly billable usage.
- Added forward-only Alembic `20260818_0033`: `actual_cost_usd` becomes nullable and a bounded `cost_basis` is persisted. Unknown actual cost is represented as SQL `NULL`, never synthetic `$0`. Downgrade safely restores the 0032 non-null contract.
- Fireworks accounting is deterministic from the current official price contract: Schnell explicitly sends a bounded `num_inference_steps` and records fixed step pricing; Kontext Pro/Max record fixed per-image pricing.
- Gemini accounting consumes Interactions `usage` modality breakdown and applies the current official input/text-output/image-output token rates for the three launch image models.
- GPT Image 2 accounting uses returned provider usage when enough token detail is present; generation without image inputs can price from text-input + image-output token counts, while edit/reference calls without modality detail keep actual cost `NULL` rather than guessing.
- Provider evidence now carries one of the governed cost bases: `official_provider_usage`, `official_fixed_step`, `official_fixed_image`, or `unknown`. Unsupported basis strings are rejected.
- Fresh PostgreSQL 16 reached Alembic `0033`; focused image authority/provider/worker accounting tests are `23/23 PASS`. Recovery `0033 -> 0032 -> 0033` PASS: `cost_basis` disappears/reappears and `actual_cost_usd` changes `NOT NULL -> NULLABLE` exactly as designed. Ruff/Mypy/compile PASS.
- This checkpoint is source/test-only. Production remains on `0032`, persistent Design Image Worker remains live-disabled, and OpenAI/Gemini/Fireworks image spend remains zero for Phase36E until this source change passes protected CI and a fresh Production backup/restore gate.

### Next safe gate

Merge protected truthful-cost source, take a fresh Production backup/restore, migrate `0032 -> 0033`, redeploy Backend/Image Worker still live-disabled, then run one bounded provider generation at a time with evidence and cleanup.
