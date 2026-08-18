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

## Checkpoint 3B — Bounded live provider acceptance and usage-evidence hardening

- Production was protected before live acceptance: merged source at `e693dfe2d6c32c3b5af124ef20b1f409f77526bf`, Alembic `20260818_0033`, Backend and non-root Design Image Worker healthy, real inherited S3 preflight passed, persistent worker remained `DESIGN_IMAGE_LIVE_ENABLED=false`, and zero image jobs existed before each one-shot canary.
- Fireworks FLUX Schnell was tested first with exactly four inference steps. The official endpoint rejected the configured launch model with HTTP `404 NOT_FOUND`: `Model not found, inaccessible, and/or not deployed`. Credential/auth/billing did not fail and no image was generated. This route is therefore live-unavailable for the current Fireworks credential/deployment and is not retried. Evidence SHA-256 `125dbfe88aa638f36387075048f0bbd4d6c92d969b5a44445a7ce7b95806d72b`.
- Gemini `gemini-3.1-flash-lite-image` is present in the authenticated model inventory. A first request proved the native Interactions output contract for this credential accepts `image/jpeg` rather than PNG; after switching to JPEG, the API returned `429 too_many_requests` with image-model free-tier quota limit `0`. This is an external API-key quota/billing-project gate, not a runtime/parser failure. No image was generated and no spend was recorded. Evidence SHA-256 `13662d0f6a13b089b9f1a1558e37167e0bcbc30d8f8c0a4f17efbcc38815ebba`.
- **OpenAI GPT Image 2 live canary PASS:** one synthetic `1024x1024`, `quality=low` generation completed through the real provider adapter -> durable image authority -> raster validation -> inherited Production S3 -> Media DAG -> StudioAssetRevision path. Runtime latency was about `22.68s`; persisted actual cost was `$0.0067` with `cost_basis=official_provider_usage`; the final raster was `826652` bytes. Media graph/node completed, Studio revision advanced `1 -> 2`, provider request evidence was present, and sensitive provider payload material was absent. Output S3 object and all synthetic DB rows were removed after evidence collection. Evidence SHA-256 `f99648bd921281b3f78178d7bbe53040bb81789016333ff147e4ebb807ed48a9`.
- All failed/successful canaries used a one-shot process that temporarily set live execution only inside that process. The persistent Design Image Worker stayed live-disabled; no unattended provider spend was armed. Post-cleanup organization/image-execution/media-graph rows returned to zero for every canary.
- Live evidence exposed one audit-quality gap: the metadata sanitizer dropped benign token-count fields because it treated every key containing `token` as secret. The sanitizer now preserves usage counters such as `input_tokens`, `output_tokens`, modality token counts and nested token details while still removing exact credential token keys (`api_token`, `access_token`, bearer/session/auth/refresh/id tokens), authorization, secrets, prompts, base64 and signed URLs. Focused durable runtime tests are `7/7 PASS` on disposable PostgreSQL 16 at Alembic `0033`; no new migration is required.
- Phase36E remains `in_progress`. One launch provider (OpenAI GPT Image 2) is live-proven. Fireworks and Gemini remain explicitly gated by current provider-side model/quota authority and are not represented as live-ready.

## Checkpoint 3B1 — Provider output-format hardening

- Gemini 3.1 Flash Lite live acceptance proved two provider-native constraints: the supported image size is 1K and the accepted output MIME is JPEG, not PNG. The bounded JPEG retry then reached the external provider quota gate (`429 too_many_requests`, image free-tier quota limit `0`), so no successful Gemini raster is claimed.
- The design capability matrix now declares output formats per provider/model. `gemini-3.1-flash-lite-image` is JPEG-only; Gemini Flash/Pro and OpenAI/Fireworks launch models keep their separately declared supported formats instead of inheriting one global assumption.
- `DesignImageExecution` validation now rejects an unsupported provider/model output format before row creation, arming, provider request or spend.
- Verification on the hardening branch: Design Factory `8/8 PASS`; focused Gemini pre-spend format guard `1/1 PASS`; Ruff and Mypy PASS on touched source. No new migration is required.
- The persistent Design Image Worker remains `DESIGN_IMAGE_LIVE_ENABLED=false`. Gemini is not retried again while the current quota gate remains unchanged, and Fireworks Schnell remains blocked by current model deployment/access.

## Checkpoint 3C — Stage 3 live image fabric closure

- Protected usage-evidence PR #435 merged as `fe5f3b4af310830e68f91ae10351e3c658a69ddb`.
- Provider-format PR #434 merged as `236372e658787e9a97f7f0c4721f9ddf83854e6d`. Production source was fast-forwarded to that commit; Backend and the non-root Design Image Worker were rebuilt/recreated from the Production compose file with `--no-deps`. The persistent worker remains `DESIGN_IMAGE_LIVE_ENABLED=false`.
- Deployed runtime verification confirms `gemini-3.1-flash-lite-image` exposes `jpeg` only and the pre-spend provider-format guard is active. Backend `/ready` is healthy; Backend and Design Image Worker healthchecks are healthy; recent critical-log hits are zero.
- **OpenAI GPT Image 2 edit/reference acceptance PASS.** A synthetic `1024x1024` PNG was stored temporarily in inherited Production S3 and referenced through a completed parent `MediaAssetNode`. A one-shot GPT Image 2 `edit` execution completed through the real provider adapter, durable authority, reference-object read, output raster validation, S3 write, Media DAG completion and Studio revision materialization.
- Edit runtime latency was about `20.62s`; actual provider cost was `$0.014912` with `cost_basis=official_provider_usage`. Persisted usage retained `input_tokens=1192`, `output_tokens=196`, and image/text input token detail keys while credential-like token fields remained redacted. Final output size was `1143998` bytes; provider request ID and checksum evidence were present.
- Edit evidence SHA-256: `9ff1e82c55aedac21b21a78e2340e5c39211298278bcda77de10780caea87259`. The synthetic source object, generated output object and all synthetic organization/image-execution/media-graph rows were removed after evidence collection.
- Provider truth at Stage 3 close: OpenAI GPT Image 2 is live-proven for generation and reference-image editing. Fireworks `flux-1-schnell-fp8` remains provider-side inaccessible/not deployed for the current credential. Gemini `gemini-3.1-flash-lite-image` remains provider-side quota-gated for the current API key; its native 1K/JPEG contract is now enforced before spend. Neither gated provider is represented as Production-live-ready.
- Current post-deploy state: Alembic `20260818_0033`; Design Image rows total/active=`0/0`; Media active=`0`; Backend and Design Image Worker healthy; persistent Design Image Worker live flag remains `false`. A pre-existing Project is in `review` at 100% and was not modified by this deployment.
- **Phase36E Stage 3 is complete. Stage 4 remains open.** Batch 36E itself remains `in_progress`; Stage 4 must finish provider-aware routing, inpaint/background/derivatives, branding/logo/infographic/diagram/experimental design outputs, editable source plus responsive export pipeline, final Production canary and closure.

## Checkpoint 4A — Fail-closed live routing and responsive export contract

- Added an explicit `ProviderRuntimeEvidence` contract that separates static capability from current live readiness. A provider/model can enter a live route only when operator/runtime evidence is `ready` and proves the exact requested operation plus provider output format. Missing, unknown, disabled or external-gate evidence never promotes a provider to live-ready.
- Added deterministic `route_live_provider(...)` selection over the existing quality/latency/cost ranking. The live route remains fail-closed for an unproven operation or output format even when the model capability matrix says the provider could theoretically support it. This means Stage 3 evidence can route OpenAI GPT Image 2 generation/edit in verified PNG form while inpaint/background-removal remain blocked until separately proven. Fireworks/Gemini external gates remain external gates rather than fallback candidates.
- Live routing can intentionally produce a bounded provider source raster for a larger governed design preset and mark `requires_resampling=true`; this prevents a high-resolution final export requirement from forcing selection of an externally gated provider when an already live-proven source route plus deterministic derivative stage is appropriate.
- Added governed `responsive_raster_exports(...)` planning over existing named presets only. Derivative filenames, dimensions, formats and cover-fit intent are deterministic; transparent-background requests never schedule JPEG derivatives. No derivative plan is represented as rendered output.
- Provider prompt packs now record a provider-native output format for Gemini and Fireworks too. Gemini Flash Lite therefore compiles to JPEG rather than inheriting an implicit PNG assumption.
- Focused Design Factory suite is `14/14 PASS`; Python compile and `git diff --check` PASS. No database migration, provider request, S3 write or Production live-arm is introduced by this checkpoint.
- The persistent Design Image Worker remains `DESIGN_IMAGE_LIVE_ENABLED=false`. Stage 4A is source/test-only and does not retry the unchanged Gemini quota gate or Fireworks model-access gate.

## Checkpoint 4B1 — Governed Sharp derivative runtime

- Stage 4A protected PR #437 passed every required/protected check, including Backend, CodeQL, Browser boundaries, dependency/container security and the full Production Docker/backup-restore job, then merged as `ccb54bcff9fbf8da29d297fc3fb5bdeb3e058888`. Production source was fast-forwarded to that merge without globally arming the Design Image Worker.
- Added a dedicated local raster derivative runtime using exact `sharp 0.35.3` on Node 24. The tool accepts only PNG/JPEG/WebP input/output, bounded dimensions, governed cover/contain fit and a small position allowlist; it refuses path aliasing and verifies source/output raster metadata before returning success.
- JPEG export fails closed when the source contains actual transparent pixels. Opaque PNGs that merely carry an alpha channel remain valid JPEG inputs, avoiding a false-positive alpha gate. Provider credentials, provider HTTP and S3 are outside this runtime.
- The Python wrapper verifies the source SHA-256 before spawning Node, validates the source raster envelope, runs Sharp in a private `0700` temporary root, verifies the returned engine/version/output format, re-inspects the final raster dimensions, and emits independent output SHA-256 plus a deterministic command-contract hash. Subprocess/provider-like stderr is never persisted as success metadata.
- The existing dedicated `media-worker` image now carries Node 24 plus the isolated Sharp tool dependency while npm is removed after installation. Its Docker build performs a real Sharp 0.35.3 synthetic PNG -> WebP transform and dimension check in addition to the existing FFmpeg 9 verification. Local candidate image `sha256:ef890e4293df10d2a969f35bbf9ced13f2b67a71cb7d362ec6cf9ac5267e4509` passed that image-level gate.
- Runtime acceptance inside the candidate image PASS: Node `24.18.1`, Sharp `0.35.3`, synthetic `80x60` PNG -> governed `640x360` WebP, with 64-character output and command hashes. Separate transparency acceptance proved transparent PNG -> JPEG is rejected. Focused Python derivative tests are `4/4 PASS`; Ruff and Mypy PASS on the new runtime/test source; `git diff --check` PASS.
- No database migration, provider request/spend, Production media object, Production worker restart or persistent Design Image Worker live-arm is part of 4B1. Fireworks/Gemini gates remain unchanged and were not retried.

### Next safe gate

Protect and merge 4B1. Then wire Sharp derivatives into the existing durable `MediaRenderStep` authority with explicit `engine=sharp` ownership and FFmpeg/Sharp claim isolation, generate child `MediaAssetNode` derivatives from completed provider-image parents, and only materialize Studio completion after all governed derivative nodes finish. Integrate the protected Stage 4A live-route evidence at execution creation; do not accept readiness evidence from user input. Inpaint/background-removal remain unarmed until separate bounded acceptance canaries.
