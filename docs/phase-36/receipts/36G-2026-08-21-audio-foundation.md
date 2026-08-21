# Phase 36G — Audio, Voice, Music, Songs & Podcast Factory

Date: 2026-08-21
Status: **IN PROGRESS — Stage 1 merged, Production-activated and no-spend Audio Studio canary accepted; Stage 2 local audio runtime pending**

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

## Protected merge and Production activation — 2026-08-21

- Protected PR #461 passed every required gate: complete Core contracts, Backend Tests, Frontend Build, Production Docker Build, Owner/VIP Browser boundaries, CodeQL Python/JavaScript, Backend SBOM/vulnerability, Dependency Security, repository secret/hygiene and Phase36 Reporting. Head `d9eee3e29440c00bec0f7ef2bafb46180691e888` merged as `d4d038ebd20f9389b5c9563a803ea6043b6c5f18`.
- Production source advanced by fast-forward only from `5ddbc08ec304582d30f549c3c6a1edc5e0ad8531` to the protected merge. No schema migration occurred; Alembic remained `20260819_0034`.
- A new Backend image was built as `sha256:7a821d47a07a2f00178fa2dc9e62e29090b3242d86234e50c2af6a5a48c588eb`. The existing Backend image `sha256:d8cbc6c9134d62534381558b345979c37601df218a6240be1ed36a174f749a11` was retained under a rollback tag.
- The long-running Studio Worker used an old image whose image metadata had already been pruned from Docker. Its exact merged root filesystem was exported before mutation, hashed, and imported as rollback image `sha256:e8dad6b56c0318d7671b10323e6bd8df208298f09a5166ec98e1a9726e0efadb`. RootFS archive SHA-256: `82220e26bb93baa7155c38c092eba7d83e06c12f56688b48f30aee9cf0e78429`; retained container configuration SHA-256: `7e7765f146aab57534cf2e11751130a0f9b5a18cad5a44e6326ef1201ca26cce`.
- Candidate validation occurred before service recreation. A `--network none` smoke generated the governed Audio Studio source package with `36G.audio-plan.v1`, six tasks, five inventory-only provider rows, no rendered audio and `external_requests=0 / external_cost_usd=$0.00`. A Compose-equivalent Studio Worker preflight passed against the real Production database and asset volume while active Studio jobs remained zero.
- Backend was recreated first and reached Healthy with `/ready` `20/20`. Studio Worker was recreated second on the same candidate image and reached Healthy. Frontend, Portal, Nginx, PostgreSQL, Redis, Media, Image, Derivative and Video service identities/start times remained unchanged.
- Post-deploy state: `current_batch=36G`, `36G=in_progress`, Alembic `0034`, active Studio/Project/Video/Media/Design queues `0/0/0/0/0`; public/portal returned HTTP `200/200`, Owner remained protected by HTTP `302`, and recent Backend/Studio critical log hits were `0/0`.

## Production Audio Studio no-spend canary

- One isolated synthetic `audio` Studio job was queued and processed by the **persistent Production Studio Worker**, not by a test-only worker. It completed in exactly one attempt with safety status `passed` and one Studio revision.
- The generated ZIP was `6,983` bytes, SHA-256 `ce445daf4c35611a939b39004ef2f9a93529682e5ed976a887e176574a785ed4`. It contained the nine governed source artifacts plus the manifest, six deterministic tasks and five provider entries all marked `inventory_visible`.
- The canary proved `provider_mode=provider_neutral`, `external_requests=0`, `external_cost_usd=$0.00`, `estimated_external_cost_usd=null`, `render_status=not_started`, no voice-rights requirement for stock narration and no `.wav/.mp3/.m4a/.webm` pretending to be rendered output.
- Cleanup removed the synthetic database scope and archive. Independent verification returned synthetic organizations/jobs/assets `0/0/0`, global active Studio jobs `0`, and matching artifact files `0`. Studio Worker health after processing was `running/healthy`, cycles/errors `1/0`, `secret_returned=false`; readiness remained `20/20`.
- Sanitized canary evidence: `.deployment-backups/phase36g-stage1-deploy/stage1-audio-studio-canary-evidence.json`, SHA-256 `7f304e0467783421c71175ac8fae3b90b290d0b383023526ebc348bbf16fdc5c`.
- Consolidated activation evidence: `.deployment-backups/phase36g-stage1-deploy/phase36g-stage1-production-activation-evidence.json`, SHA-256 `c00a8d957532afbca3887324e4b41faf73fb7db17c001eded63f4b1dd30f14f6`.
- Rollback-boundary metadata SHA-256: `57edbc793f32749ef8587139483c24ed23f215b10ae0e7a2645fb6708b226677`.

## P36-0019 — Canary cleanup verifier referenced the Organization model with the wrong scope column

- Batch/environment: Phase 36G Stage 1 Production no-spend canary, after successful asset validation.
- Symptom: the canary process exited non-zero during its final verification loop because it tried `Organization.organization_id`; the Organization table is keyed by `Organization.id`.
- User impact: none. The Studio job had already completed, the pre-cleanup checkpoint had already been atomically written, and database/file cleanup had already committed before the faulty verification expression ran. No provider request or spend occurred.
- Root cause: a generic post-cleanup count loop assumed every scoped model exposes `organization_id`; `Organization` is the single root model and instead requires `id == synthetic_org_id`.
- Detection/evidence: the retained checkpoint proved the completed ZIP/manifest/plan before cleanup. Direct independent queries then proved synthetic organizations/jobs/assets `0/0/0`, active Studio jobs `0`, and no matching artifact file. Studio Worker remained Healthy with errors `0`.
- Fix: the external canary script now selects `Organization.id` for the root model and `model.organization_id` for all tenant-scoped child models. The job/provider operation was **not rerun**.
- Regression prevention: future destructive canaries must write a validated-before-cleanup checkpoint, use model-specific cleanup predicates, and independently verify both database and object/file absence before declaring PASS.
- Final result: deployment and canary remain PASS; the script failure was confined to the post-cleanup verifier and is explicitly retained in the final evidence.

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
