# Phase 36E — Image, design, branding, infographic & prompt factory

Date: 2026-08-18
Status: **IN PROGRESS — latest-provider design foundation checkpoint**

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
