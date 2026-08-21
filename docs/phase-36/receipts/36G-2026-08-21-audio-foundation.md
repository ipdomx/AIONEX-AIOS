# Phase 36G — Audio, Voice, Music, Songs & Podcast Factory

Date: 2026-08-21
Status: **IN PROGRESS — Stage 1 provider-neutral planning, rights/consent and QA foundation complete; no external audio execution or spend**

## Truth boundary

This checkpoint creates a deterministic source/planning contract. It does **not** claim that speech, transcription, dubbing, music, vocals, SFX, a transformed voice or a cloned voice has been rendered by an external provider.

Stage 1 performs no provider request, reads no provider credential and estimates no provider cost. Every generated Studio package remains `provider_neutral`, records `external_requests=0`, `external_cost_usd=0`, `estimated_external_cost_usd=null`, and exposes `render_status=not_started`.

The Phase 36 registry remains truthful:

- `36G=in_progress` and `current_batch=36G`;
- `stt-tts-dubbing`, `audio-cleanup-master`, and `podcast-jingle-narration` remain `source_built`;
- `voice-transformation` and `song-production` remain `specified`;
- no 36G capability is promoted to `provider_connected`, `runtime_verified`, `scaled`, or `production_ready` by this source-only checkpoint.

## Implemented governed audio factory

New module: `src/aios/audio_factory.py`.

The factory supports ten user-level project contracts:

1. transcription;
2. speech;
3. dubbing;
4. narration;
5. podcast;
6. jingle;
7. song;
8. cleanup/master;
9. consent-governed voice transformation;
10. consent-governed voice cloning.

Each request compiles into a deterministic, topologically ordered Audio Task DAG. Composite workflows are decomposed rather than represented as one opaque provider call:

- transcription: ingest → analyze → transcribe → optional diarization → QA → package;
- dubbing: ingest → analyze → transcribe → optional diarization → translate → synthesize → align → mix → master → QA → package;
- narration/speech: script → synthesize → cleanup → master → QA → package;
- podcast: script → multi-speaker synthesis → optional music/SFX → mix → master → QA → package;
- song/jingle: script → composition → vocals → optional SFX → mix → master → QA → package;
- voice transform/clone: ingest → rights gate → governed voice operation → QA → package.

Provider-required tasks with no truthful provider route become explicit `provider-runtime:<operation>` gates. They do not silently fall back, fabricate an output, or imply that a connected generic AI provider is ready for an audio endpoint.

## Official capability inventory — visibility is not readiness

Stage 1 records an official-source inventory for provider-neutral planning only:

- OpenAI `gpt-audio` — official model source `https://developers.openai.com/api/docs/models/gpt-audio`;
- OpenAI `gpt-realtime-1.5` — official model source `https://developers.openai.com/api/docs/models/gpt-realtime-1.5`;
- Google Gemini audio understanding/transcription inventory — official guide `https://ai.google.dev/gemini-api/docs/audio`;
- Gemini `gemini-2.5-flash-preview-tts` — official model source `https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-preview-tts`;
- Gemini `gemini-2.5-pro-preview-tts` — official model source `https://ai.google.dev/gemini-api/docs/models/gemini-2.5-pro-preview-tts`.

All rows are exposed as `inventory_visible`, never `ready`. A separate `AudioRuntimeEvidence` contract is required before runtime routing. A route may become ready only when exact provider/model/operation evidence exists; duplicate evidence and generic inventory-only evidence fail closed.

No music-composition, vocal-generation, SFX-generation, voice-transformation, or voice-cloning provider is invented. Consequently song/jingle plans remain explicit external gates and voice operations remain unavailable for execution.

No prices are embedded in the capability matrix. Cost remains unknown until a later provider-specific bounded route obtains official pricing and explicit operator approval.

## Voice rights and consent contract

`VoiceRightsEvidence` stores hashes and scope, not raw identity or consent media:

- SHA-256 subject reference;
- SHA-256 consent evidence;
- rights basis: self, licensed performer, or verified provider share;
- allowed operations and allowed purposes;
- timezone-aware issuance/expiry;
- revocability and optional revocation time;
- optional SHA-256 provider identity-verification reference.

The gate validates operation, purpose, issuance, expiry, and revocation at the execution time supplied by the caller.

Voice transformation cannot be planned without valid scoped consent/rights evidence. Voice cloning is stricter:

- licensed-performer evidence alone is rejected;
- self rights require a later provider identity-verification gate;
- a verified-provider-share requires a hashed provider verification reference;
- even valid rights are necessary but not sufficient: Stage 1 has no verified clone provider, so `provider-runtime:voice-clone` remains blocking.

Public snapshots contain no raw subject name, raw voice sample, consent recording, credential, authorization header, signed URL, or provider secret.

## Output and QA contracts

The factory exposes governed output profiles with granular runtime truth:

- `wav-pcm-48k-stereo`: `runtime_verified` through the existing Phase 36D FFmpeg 9.0 media path;
- `wav-pcm-48k-mono`: `source_built`;
- `m4a-aac-48k-stereo`: `source_built`;
- `webm-opus-48k-stereo`: `source_built`.

Source-built does not mean an end-to-end audio project was executed. Only the existing stereo WAV media profile has prior runtime evidence; the others remain unaccepted Stage 36G outputs.

Every plan includes a QA policy contract for:

- output profile/sample rate/channels;
- integrated loudness policy target;
- true-peak ceiling;
- loudness-range ceiling;
- waveform generation;
- EBU R128 scan;
- silence scan;
- clipping scan;
- transcript requirement for speech-bearing workflows.

The QA contract identifies future FFmpeg work. Stage 1 does not claim that `loudnorm`, `ebur128`, silence, or clipping analysis has been executed for an AudioFactory project.

## Production Studio integration

Audio Studio now emits editable/auditable source artifacts:

- `audio/narration.txt`;
- `audio/narration.ssml`;
- `audio/audio-plan.json`;
- `audio/task-graph.json`;
- `audio/provider-inventory.json`;
- `audio/qa-contract.json`;
- `audio/rights-manifest.json`;
- `audio/cue-sheet.json`;
- `audio/mix-notes.md`.

The package deliberately contains no `.wav`, `.mp3`, `.m4a`, or `.webm` pretending to be rendered output. The archive manifest remains provider-neutral with zero external requests/cost.

The cue sheet stores text SHA-256 and length instead of duplicating script content. The SSML remains an editable provider-neutral template. Mix notes state that no rendered audio is claimed and that provider cost is unknown until a later bounded route is armed.

## Verification and isolated full-suite evidence

Completed against the current Stage 1 source:

- AudioFactory focused tests: `12/12 PASS`;
- AudioFactory + VideoFactory + Phase36 governance regression: `33/33 PASS`;
- complete AIOS Core suite: `761/761 PASS` in `30.06s`;
- Backend-focused Production Studio/Phase36 contracts: `12/12 PASS`;
- current-source Audio Studio runtime contract inside the real Backend dependency environment: PASS;
- generated Audio Studio archive was valid and provider-neutral, with all nine governed source artifacts, `external_requests=0`, `external_cost_usd=0`, `estimated_external_cost_usd=null`, `plan_status=planned`, `render_status=not_started`, six narration tasks and five unique inventory-visible provider rows;
- Backend Ruff: PASS;
- Backend Mypy: PASS across `207` source files;
- Backend verification/compile: PASS;
- full Backend suite on disposable PostgreSQL 16 + Redis 7 at Alembic `20260819_0034`: **`799 passed, 2 warnings, 0 failed`** in `299.15s`;
- Backend coverage: `65.06%`, above the enforced `22%` floor;
- PostgreSQL connection-exhaustion/deadlock/PANIC/FATAL hits: `0`;
- Redis ERR/OOM/panic/fatal hits: `0`;
- disposable containers/network were removed after the run;
- Python compile and `git diff --check`: PASS.

Retained isolated evidence outside Git:

- `.deployment-backups/phase36g-stage1-tests/backend-full-20260821T215354Z.log` — SHA-256 `0aaafd4005506f28f9cf58a8160ff125e1f542444b12d75ab75c12140088f469`;
- `.deployment-backups/phase36g-stage1-tests/backend-full-20260821T215354Z.json` — SHA-256 `0a7471c2b2b8135afc7270ad5dd997cde72489df02fc7399b6703c975eb8cfbe`, status=`pass`.

No Production service, schema, data row, provider credential, provider request or provider spend was touched by this validation.

## P36-0018 — Isolated Backend harness failed before tests because the validation image/mount/PATH contract was stale

- Batch/environment: Phase 36G Stage 1 local isolated validation; Production untouched.
- Symptom: pre-test harness attempts failed before application tests: one older image lacked the current dependency/runtime contract, a read-only source mount prevented `compileall` bytecode writes, and the first current-image command used a login shell that reset `/opt/venv/bin` from `PATH`, producing `alembic: not found`.
- User impact: none. No Production container, database, provider or user workload was changed, and no functional project test had failed.
- Root cause: the local harness reused assumptions from older Backend images and treated source as read-only even though the repository verification script intentionally compiles it. The login-shell invocation also overrode the image's venv path.
- Why safeguards did not prevent it: focused tests used already-running dependency environments and therefore did not exercise the exact fresh CI test-target startup contract.
- Fix: build the current `web-dashboard/backend/Dockerfile --target test`; copy the current Worktree to a writable temporary repository; set `PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin` explicitly; run fresh PostgreSQL/Redis services; hash retained logs/metadata; and remove every disposable resource after completion.
- Regression prevention: future Phase36 full Backend gates must use the current Dockerfile test target, a writable temporary source copy, explicit venv PATH, fresh isolated data services, retained log hash and post-run resource cleanup assertion.
- Final result: corrected harness completed `799/799` Backend tests with `65.06%` coverage and zero PostgreSQL/Redis critical hits.

## External and legal gates retained

- no voice transformation or cloning without valid rights/consent evidence;
- no clone route without provider identity verification and exact runtime evidence;
- no song/jingle finality until composition, instruments, vocals, stems, mix and master have separated runtime evidence;
- no paid provider execution without official pricing, exact request cap, explicit operator approval and cleanup evidence;
- no maturity promotion from capability inventory alone.

## Next safe gate — Stage 2

Build a local, provider-neutral AudioExecution/Media DAG path before any paid provider route:

1. deterministic local WAV fixtures and tenant-scoped graph nodes;
2. FFmpeg 9.0 cleanup, resample, align, mix and master primitives;
3. waveform, EBU R128, silence and clipping evidence;
4. crash-safe retry/idempotency and selective failed-step regeneration;
5. final WAV/AAC/Opus artifact materialization and Studio revision;
6. bounded cleanup with all synthetic rows/objects returned to zero.

Stage 2 must remain provider-spend `$0.00`. Only after that local path passes should a separately reviewed Stage 3 consider one bounded STT/TTS provider route. Voice transformation/cloning and song/music-provider execution remain later consent/legal/provider gates.
