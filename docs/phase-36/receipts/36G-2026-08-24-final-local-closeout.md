# Phase 36G — Final local closeout and external-gate transfer

Date: **2026-08-24**  
Status: **LOCAL CLOSEOUT COMPLETE — 36G is externally gated, 36H becomes the active development batch**

## Decision

Phase 36G is not marked `complete`, because its published exit contract requires one real complete-song runtime acceptance with separated evidence for lyrics, composition, synthetic vocals, four stems, mix, master and final export. That provider boundary has not passed. The batch is instead moved from `in_progress` to the explicit status `external_gate`.

This is not a maturity promotion. It is a truthful scheduling transition: every remaining 36G capability is either runtime-evidenced or bound to a named external acceptance/funding/rights gate, so no unclassified local engineering work remains. Phase 36H becomes `in_progress` and the public non-secret registry exposes 36G in `external_gate_batches`.

## Local closure matrix

The already accepted granular runtime boundaries remain unchanged:

- pinned stock-voice TTS and single-speaker narration with governed local mastering/export;
- single-speaker STT, pseudonymous multi-speaker diarization and timed caption packaging;
- complete stock-voice dubbing with translation, per-segment TTS, timing-fit alignment, mix and final master;
- local cleanup, alignment, mixing, loudness QA, waveform and governed export;
- bounded Stable Audio instrumental generation and local Studio materialization;
- hard-disabled durable open-song authority, one-attempt RunPod worker, immutable runtime binding contract, four-stem ingestion and FFmpeg finalization.

The registry now names every unresolved capability and its exact gate:

- broad STT/TTS/dubbing aggregate: aggregate runtime acceptance;
- voice transformation: valid consent/rights plus a provider runtime acceptance;
- voice cloning: self-owned or provider-verified rights, provider identity verification and runtime acceptance;
- Lyria: positive Replicate billing or Gemini paid generation quota, then real Lyria audio acceptance and SynthID/rights disclosure;
- dedicated SFX: provider runtime acceptance plus commercial rights/disclosure;
- complete songs: available ACE-Step ZeroGPU quota or a funded RunPod open-song Endpoint, then full runtime acceptance and rights/disclosure;
- podcast/jingle aggregate: multi-speaker podcast, music/vocal jingle and dedicated-SFX runtime acceptances.

`phase36_program_snapshot()` now reports per batch:

- `local_closeout_complete`;
- `blocking_external_gates`;
- `unresolved_capabilities`;
- `ungated_unresolved_capabilities`.

For 36G, `local_closeout_complete=true` and `ungated_unresolved_capabilities=[]`. This invariant prevents a wide aggregate capability from silently remaining incomplete without a precise gate.

## Final ACE-Step external-boundary evidence

The current official ACE-Step Space was checked read-only before the final attempt. Its Gradio API was reachable and exposed both Turbo and XL model choices. Current official Space, Turbo-model and 4B language-model revisions remained pinned. Read-only preflight generated no audio request and no spend.

- official Space preflight SHA-256: `8145ac1ea8420edf4f8defe1f514571adab418a3660fb5e4e4bc2f50b6c65a2e`;
- current Hugging Face revision evidence SHA-256: `e45ffc6341aa29a20c90ef14ef0931fc1f0f519a41c96aadf9d22a5239a5d6ec`.

One fresh, separately authorized authenticated Turbo request was then submitted with `batch_size=1`, deterministic seed, a 15-second bound and no automatic retry, resubmit or provider fallback. It ended in `AppError`, classified as unavailable GPU quota. No audio was returned and provider spend was `$0.00`.

- attempt-state SHA-256: `f219c06cb28761a6901f1f56ef35ea47995ab5f5d7cd2e06e169432a357d40e4`;
- provider-result SHA-256: `b0c6b198b37adf0a4f39f397017b675b5727f66748d92965dc8be6197c330d10`;
- sanitized classification SHA-256: `2d5a21e9fef6adbd24ca517c6f00b7af1eab3ce42ac88f449837b2eebe18e448`.

The temporary acceptance container and temporary credential file were removed immediately. This was the fourth separately invoked official-Space attempt across Stage 8; none was retried automatically and none returned accepted audio.

## RunPod external boundary

A read-only RunPod account and Endpoint inventory proved:

- client balance: `-$0.0120109142`;
- current fixed spend: `$0.019/hour`;
- no open-song Endpoint exists;
- the existing Endpoints are unrelated 3D boundaries and have `workersMin=0`;
- no Endpoint, template, worker or GPU Job was created by this closeout.

RunPod balance evidence SHA-256: `3529b78fdb1fb1746e2fe4e449b58bb2e1916e8cf793bf75451b1032be1deecd`.  
RunPod inventory evidence SHA-256: `799ffc1add555169a46651e21af55f0318905d73415310dd1a19a14884504675`.

The paid route therefore remains hard-disabled. A RunPod acceptance is legal only after a positive funded balance, a separately built/SBOM-verified immutable handler image, a dedicated open-song Endpoint with zero minimum workers, and an explicit one-attempt approval.

## Production safety at closeout preparation

Before the registry transition:

- source and `origin/main` were aligned at `09ea3fb49235ef64a97fabae7de205caa7342d47`;
- Backend and the permanent Audio Song Worker were Healthy;
- the Song Worker remained internally `disabled`, with zero cycles/errors;
- Alembic was `20260823_0039`;
- `audio_song_executions` total/active rows were `0/0`;
- the final Space attempt caused no Production mutation, GPU Job or pending provider cost.

## P36-0097 — Browser fixture retained the prior current batch

The first protected Browser run passed ten of eleven boundaries and failed only the Phase 36 projects assertion: its mocked API had already moved to `current_batch=36H` and `total_capabilities=63`, while the final visible-text assertions still expected `36G` and `1/60`. The correction updates only those two truthful fixture assertions to `36H` and `1/63`; no browser route, retry, authentication, layout or production behavior is weakened. The other ten browser boundaries had already passed, and the failing run caused no provider request or Production mutation.

## Transition contract

After protected merge and Backend registry activation:

- `36G.status = external_gate`;
- `36G.local_closeout_complete = true`;
- `36G.ungated_unresolved_capabilities = []`;
- `36H.status = in_progress`;
- `current_batch = 36H`;
- `external_gate_batches = ["36G"]`.

Phase 36G may move from `external_gate` to `complete` only after the published full-song exit evidence passes. Reopening it for source refactoring without a proven regression or newly satisfied external gate is prohibited.
