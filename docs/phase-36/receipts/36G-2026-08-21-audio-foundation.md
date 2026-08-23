# Phase 36G — Audio, Voice, Music, Songs & Podcast Factory

Date: 2026-08-21
Updated: 2026-08-23
Status: **IN PROGRESS — Stages 1–6 Production-accepted; Stage 7 direct Gemini route quota-blocked, durable same-price Replicate Lyria fallback source candidate validated with zero new generation/spend**

## Truth boundary

This checkpoint separately claims the Production-accepted pinned stock-voice TTS, single-speaker STT, pseudonymous multi-speaker diarization, and complete bounded stock-voice dubbing routes. Stage 7 source and its hard-disabled Production authority are deployed at Alembic `20260823_0038`, but no Lyria audio has been accepted: the valid Gemini key can read the exact Clip/Pro models and run `countTokens`, while every bounded Clip generation attempt was rejected by Provider quota before an output existed. Podcasts/jingles, accepted live music generation, dedicated SFX, stems, transformed voice and cloned voice remain outside the accepted claim.

Stage 1 performs no provider request, reads no provider credential and estimates no provider cost. Every generated Studio package remains `provider_neutral`, records `external_requests=0`, `external_cost_usd=0`, `estimated_external_cost_usd=null`, and exposes `render_status=not_started`.

The Phase 36 registry remains truthful:

- `36G=in_progress` and `current_batch=36G`;
- `audio-cleanup-master`, granular `stock-voice-tts`, granular single-speaker `governed-stt-transcript`, granular `multi-speaker-diarization`, and granular `complete-stock-voice-dubbing` are `runtime_verified`; broader `stt-tts-dubbing` and `podcast-jingle-narration` remain `source_built`;
- granular `lyria-3-music-generation` and `stable-audio-instrumental-generation` are `source_built` behind provider/runtime/rights disclosure gates; `voice-transformation` and broad `song-production` remain `specified`;
- no other 36G capability is promoted to `provider_connected`, `runtime_verified`, `scaled`, or `production_ready`; Phase 36G remains `in_progress`.

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

## Stage 2 — local provider-neutral audio runtime candidate

Stage 2 reuses the existing Phase 36D `MediaAssetGraph`, `MediaAssetNode`, `MediaRenderStep`, object-storage, lease/fencing and Studio revision authorities. It adds **no new database table or migration** and does not create a second audio job system.

### Local AudioPlan → Media DAG bridge

`app.services.audio_pipeline` accepts only the Stage 1 `cleanup-master` operation. Provider-dependent tasks such as STT, TTS, dubbing, composition, vocals, SFX, voice transformation and voice cloning cannot enter this local path.

Each tenant-scoped source is required to be:

- completed;
- owned by the same organization;
- a governed audio media type;
- backed by an existing storage backend/key;
- accompanied by exact size and SHA-256 evidence.

A one-to-eight-source project becomes the deterministic graph:

`governed source → cleanup → alignment → mix → master → waveform + final export`

For multiple sources each source receives independent cleanup/alignment nodes. The final export depends on both the completed master and the PNG waveform evidence, while the master is ordinal `0`, so Studio materializes the governed audio output rather than the QA image.

The idempotency fingerprint binds the AudioPlan checksum, graph checksum, source node identities/checksums, offsets and gains. Reusing the same key with a changed source, offset or gain fails closed.

### FFmpeg 9 local execution

The shipped FFmpeg runtime now verifies the exact local audio filter surface before accepting work:

- `highpass` / `lowpass` cleanup;
- `aresample` and channel-layout normalization;
- `adelay` alignment;
- `amix` plus bounded limiter;
- `loudnorm` / EBU R128 analysis;
- `silencedetect`;
- `astats` clipping/sample-peak evidence;
- `showwavespic` waveform generation.

New governed output profiles are:

- 48 kHz stereo PCM WAV;
- 48 kHz mono PCM WAV;
- 48 kHz stereo AAC/M4A at `192 kbps`;
- 48 kHz stereo Opus/WebM at `128 kbps`.

Codec, container, sample rate and channel count are checked with FFprobe. Final master/export QA emits `36G.audio-qa.v1` with integrated LUFS, true peak, loudness range, sample peak, silence count/duration and clipping status. Raw FFmpeg logs are not retained in graph/public evidence.

### Isolated integration and real-image evidence

- Disposable PostgreSQL 16 + Redis 7 at Alembic `20260819_0034`: new audio runtime plus affected Phase36D/36F regression **`38/38 PASS`**; PostgreSQL/Redis critical hits `0/0`.
- The tests prove full DAG completion, one Studio revision, exact profile mapping, tenant isolation, source/timeline idempotency, stale-worker fencing, and a partial revision that changes only `align-001` plus downstream `mix/master/waveform/export` while preserving the unaffected `align-002` checksum/provenance.
- Ruff: PASS across the complete Backend app/tests/scripts surface.
- Mypy: PASS across `208` Backend source files.
- Complete AIOS Core: `761/761 PASS` in `31.30s`.
- Fresh current-source Backend test image: `sha256:0a1a9e1aa3521d3f13241b2df56b7f0c515136f115403c50d5818a3e604720ad`; build-log SHA-256 `2aa14cc9b458bb0882b4c45dddb27f602ed4e43256a9553984ee2a095d8df1c0`.
- Full Backend on a second fresh PostgreSQL 16 + Redis 7 environment: **`809 passed, 2 warnings, 0 failed`** in `307.09s`; coverage `64.92%`; PostgreSQL/Redis critical hits `0/0`; disposable containers/network removed.
- Full Backend log SHA-256 `fd6a6396b1ca8a756f369f5329eb46b262ef62f3acbcad7440333fad74ca7f90`; metadata SHA-256 `4467245702debe58af52928b2142dbab36d48c5f638f471f5f9ca45e8571bb45`, status=`pass`.
- Workflow YAML, Python compile and `git diff --check`: PASS.
- A real `--network none` Media Worker image built as `sha256:ddb231abc5ff1797c4b7f76835db162b2108e1b23ea2c927cc135554e463ba26` executed two WAV sources through cleanup, delayed alignment, mix, master, waveform and all four exports.
- Real measured integrated loudness: master `-15.97 LUFS`, stereo WAV `-16.04`, mono WAV `-16.04`, AAC `-16.05`, Opus `-16.05`; all remained inside the unchanged `1.5 LU` tolerance, passed true-peak/LRA/clipping/silence checks and retained `provider_requests=0 / provider_spend_usd=$0.00`.
- Final real-image build log SHA-256: `e4deec3c32fb15fe3e990bd95a9c0681ad2c29f8e414b62dfdc2f2c157d6a4e3`.
- Final real-image smoke evidence SHA-256: `afec9c6930d612a04dcd6de9ac10fd2667d6d089ef89fd3090ef3a95b7d0e7e1`.

This candidate evidence alone did not promote maturity; the later protected Production acceptance and granular promotion decision are documented below.

## P36-0020 — Mono export loudness normalization ran before channel downmix

- Batch/environment: Phase 36G Stage 2 real FFmpeg 9 candidate-image smoke; Production untouched.
- Symptom: stereo WAV, AAC and Opus exports stayed near the `-16 LUFS` target, but the mono WAV measured approximately `-18.97` to `-19.04 LUFS` and the strict `1.5 LU` gate rejected it.
- User impact: none. The failure occurred in an isolated `--network none` candidate container before protected merge/deployment; no provider request, provider spend, Production asset or user job existed.
- Detection/evidence: the real image smoke failed closed at `audio master failed governed QA: integrated_loudness`. A diagnostic with a temporarily wider measurement window confirmed that the mono-only deviation was about `3 LU`, while all other formats remained near target.
- Root cause: `audio_export` applied `loudnorm` to the stereo master and only then converted the output to mono. Downmix changed perceived integrated loudness after normalization, so the final encoded signal no longer met the requested target.
- Why prior tests missed it: FakeFFmpeg integration tests validate scheduling, fencing, provenance and profile contracts; they do not model channel-dependent EBU R128 behavior. Historical Phase36D runtime evidence covered stereo WAV only.
- Fix: convert/resample to the final channel layout first, then run `loudnorm` on that final-layout signal, resample once more and encode. The QA tolerance was **not widened** and remains `1.5 LU`.
- Regression prevention: Production Docker CI now runs the complete Stage 2 audio chain inside the real Media Worker with `--network none` and requires WAV stereo/mono, AAC and Opus to pass `36G.audio-qa.v1` independently.
- Final result: real rerun passed with mono `-16.04 LUFS`; all four formats passed codec/container/rate/channels/loudness/peak/LRA/clipping/silence checks with zero provider activity.

## External and legal gates retained

- no voice transformation or cloning without valid rights/consent evidence;
- no clone route without provider identity verification and exact runtime evidence;
- no song/jingle finality until composition, instruments, vocals, stems, mix and master have separated runtime evidence;
- no paid provider execution without official pricing, exact request cap, explicit operator approval and cleanup evidence;
- no maturity promotion from capability inventory alone.

## Stage 2 protected merge and Production activation — 2026-08-22

- Protected PR #463 passed every required gate: Core, Backend, Frontend, Production Docker, the FFmpeg 9 four-format no-network audio smoke, Owner/VIP browser boundaries, CodeQL Python/JavaScript, Backend SBOM/vulnerability, Dependency Security, repository secret/hygiene and Phase36 Reporting. Head `a45ac64f4c8f6e848b54385f240eb07d30b3611b` merged as `998fab35cee414d495050c352ff43667c2cff3ae`.
- Production source advanced by fast-forward only from `b636105914c709ecb8aca105e2fe4314fc49ed2f` to the protected merge. No migration was introduced; Alembic remained `20260819_0034`.
- The prior Media Worker image `sha256:75704791b57e2743a39ec74e9132fc181caa060e37a4104585cbbd2764afcf3d` was retained as `aionex-aios-media-worker:rollback-phase36g-stage2-20260821T234531Z`. The merged candidate was built as `sha256:cd0551d4606dab2f4c189ec374fca02f7f60340c46f20c61e09cb5c06670a3a9`.
- A Compose-equivalent candidate preflight touched the real Production database/object volume read-only except for the storage writability probe, called no claim path, and kept active Media steps `0 → 0`. It proved FFmpeg `9.0`, software-only operator policy, the governed encoders and all required Stage 2 audio filters.
- The exact merged candidate then passed a second `--network none` smoke. WAV stereo/mono, AAC/M4A and Opus/WebM plus a `1200×320` PNG waveform passed codec/container/rate/channel and `36G.audio-qa.v1` checks. Measured integrated loudness remained master `-15.97`, WAV stereo/mono `-16.04`, AAC/Opus `-16.05 LUFS`; provider requests/spend stayed `0 / $0.00`.
- Only `web-dashboard-media-worker-1` was recreated. It moved from container `645073d9...` / old image `75704791...` to container `00603ac0...` / candidate image `cd0551d4...` and reached Healthy. Backend, Studio Worker, PostgreSQL, Redis, Image, Derivative, Video, Frontend, Portal and Nginx identities/start times remained unchanged.

## Stage 2 persistent Production Worker canary

- One synthetic tenant scope supplied two real governed WAV fixtures to four independent local DAGs. The persistent Production Media Worker—not a test worker—produced:
  - stereo PCM WAV: `432,078` bytes, `48 kHz`, 2 channels, `-16.00 LUFS`;
  - mono PCM WAV: `216,078` bytes, `48 kHz`, 1 channel, `-16.00 LUFS`;
  - AAC/M4A: `55,832` bytes, `48 kHz`, 2 channels, `-16.00 LUFS`;
  - Opus/WebM: `40,142` bytes, `48 kHz`, 2 channels, `-16.00 LUFS`.
- Every output and master passed loudness, true-peak, LRA, clipping and silence evidence under `36G.audio-qa.v1`; every graph also produced a real PNG waveform and advanced its bound Studio asset to revision `2`.
- Durable crash recovery was exercised without provider work: a synthetic first step was committed as an expired `running` lease owned by a simulated crashed worker. The persistent worker reclaimed the same step with `attempts=2`, fencing `1 → 2`, replaced the stale owner and completed the graph; all unaffected steps remained single-attempt.
- A partial revision changed only `align-001` offset. The affected set was exactly `align-001 → mix → master → waveform → export`; `align-002` was reused with the identical checksum and `reused-render` provenance. The final export checksum changed and Studio advanced from revision `2` to `3`.
- A validated-before-cleanup checkpoint was written before deletion. Cleanup deleted and independently verified missing `45/45` object keys, removed every synthetic Organization/User/Studio/Media/Provider row and returned global active Media steps to `0`.
- Post-canary Worker health was `running/healthy`, FFmpeg `9.0`, cycles/errors `43/0`, `secret_returned=false`. All queues were `0`, `/ready` passed `20/20`, public/portal returned `200/200`, Owner remained protected by `302`, and Backend/Studio/Media critical-log hits were `0/0/0`.

### Stage 2 evidence

- Candidate preflight SHA-256: `2b21eed3f3f958491bac32b6059b5f5c9ffc5bcdcb29d05f03c1292636e9d15b`.
- Merged-candidate no-network smoke SHA-256: `45d164c153acd4565100fd3c051f99a90ed1f6624d73e085f9022e0abcfc9894`.
- Media Worker recreation evidence SHA-256: `c7add66bde52c6fa860af4f78dee9e82e2f34ad43a8eedf0d6d0f64e4c682523`.
- Validated-before-cleanup canary checkpoint SHA-256: `60ea4986750fe220f75beb9f0f826e3bd395707ee636fe2a225ee04af040e016`.
- Final sanitized canary evidence SHA-256: `162b8d0bb83bb2d1119994c98e1037b30afaf8020a853bc85c02c70cef88cd43`.
- Consolidated Production activation evidence: `.deployment-backups/phase36g-stage2-deploy/phase36g-stage2-production-activation-evidence.json`, SHA-256 `76bf194dca4bff3328d91c439d1809c91d62e92005073b2f96730d7b884d3f29`.

## P36-0021 — Production preflight wrapper initially used the wrong interpolation file and host Python alias

- The first wrapper attempt stopped before creating a container because Compose interpolation used `.env`, which intentionally lacks required Production values. A corrected run used `.env.production`; its in-container preflight passed, but the wrapper then exited while formatting the already-written evidence because the host exposes `python3`, not `python`.
- No claim, database mutation, service restart, provider request or spend occurred in either wrapper failure. The valid preflight file was parsed and verified instead of repeating work.
- The permanent rule is: Production Compose probes must pass both `--env-file .env.production` and the absolute `AIOS_ENV_FILE`, and host evidence tooling must call `python3` explicitly.

## Stage 2 maturity decision

Only `audio-cleanup-master` advances from `source_built` to `runtime_verified`. This decision is supported by protected source, exact merged-image smoke, persistent-worker execution, crash recovery, selective partial revision, final Studio materialization and complete cleanup evidence.
The capability title is deliberately bounded to cleanup, alignment, mixing, mastering and governed local export; generated SFX remains outside this runtime-verified claim and stays a later provider gate.

The following claims do **not** advance:

- `stt-tts-dubbing` remains `source_built` because no provider STT/TTS execution has been accepted;
- `podcast-jingle-narration` remains `source_built` because no complete provider-rendered narration/podcast/jingle reached final audio;
- `song-production` and `voice-transformation` remain `specified`;
- voice cloning/transformation remains blocked by consent, rights, provider identity and exact runtime evidence;
- Phase 36G remains `in_progress`.

## Stage 2 maturity-status protected merge and Backend activation — 2026-08-22

- Protected PR #464 passed every required gate and merged head `d614dc173eea3189f5ff3fddecdd76fe5bb3e80a` as `c5f07e5c2fcddd187ef5563749e3b70fd8a221d7` at `2026-08-22T00:54:25Z`.
- Production source advanced by fast-forward only from `998fab35cee414d495050c352ff43667c2cff3ae` to the protected merge. The delta was limited to the Phase36 registry/tests and Stage 2 receipt/roadmap; no migration was present and Alembic remained `20260819_0034`.
- The previous Backend image `sha256:7a821d47a07a2f00178fa2dc9e62e29090b3242d86234e50c2af6a5a48c588eb` was retained as `aionex-aios-backend:rollback-phase36g-stage2-status-20260822T005526Z`. The protected source built Backend image `sha256:90f278da05003f19a657e521967432b0f39f50571509e6d7f06d101ea92455e7`.
- A candidate smoke ran with `--network none` and proved the exact granular registry plus all four local audio-profile mappings. A second candidate preflight against the real Production database remained read-only, kept every active queue `0 → 0`, and observed Alembic `0034`.
- Only `web-dashboard-backend-1` was recreated. It moved from container `cce877de...` to `84b1093f...` and reached Healthy. Studio Worker, Media Worker, PostgreSQL, Redis, Image, Derivative, Video, Frontend, Portal and Nginx identities/start times remained unchanged.
- The live Backend function and direct HTTP endpoint `/api/v1/capabilities/phase36` now both report `audio-cleanup-master=runtime_verified`, while STT/TTS and podcast remain `source_built`, song and voice transformation remain `specified`, and `36G=in_progress/current_batch=36G`.
- Direct Backend HTTP returned `200 application/json`. The existing public Nginx boundary returned `404` for the same capability path; this activation deliberately did not widen ingress exposure.
- Post-activation: queues `0/0/0/0/0`, Media Worker unchanged/Healthy with FFmpeg `9.0`, cycles/errors `43/0`, readiness `30/30`, public/portal `200/200`, Owner `302`, and Backend/Studio/Media critical-log hits `0/0/0`. No provider request or spend occurred.
- Final sanitized activation evidence: `.deployment-backups/phase36g-stage2-status-activation/phase36g-stage2-status-production-activation-evidence.json`, SHA-256 `98b36ed7a771485ca91dbbf1ada91d3ca659f697525cd19a86d5e747696e2d8c`.

## P36-0022 — Offline Backend smoke omitted Docker stdin attachment

- The first `--network none` Backend smoke launched `python -` without Docker `-i`; therefore the script received no source, exited without executing the assertions and produced an empty output file. The subsequent JSON formatter—not product code—reported the failure.
- No network, database connection, service restart, provider operation or Production mutation occurred. The empty artifact was removed and the exact same candidate smoke was rerun with `docker run -i`, producing valid evidence SHA-256 `805d089b4910c46622ae757d8f7bca36d0d991375802f49586ede158aa4d8231`.
- Future heredoc-driven Docker probes must attach stdin explicitly and reject empty evidence before parsing.

## PR #465 truth-boundary correction activation — 2026-08-22

- While PR #466 was being rebased, protected PR #465 had already merged as `a9bd80c7acb414f39e4f1307d304cf28657f9839` and Production had already fast-forwarded to it. The existing Backend container ID remained `84b1093f...`; its `StartedAt` advanced to `2026-08-22T01:27:40.84899332Z` on the same image `90f278da...`.
- The correction narrows the runtime-verified title to **audio cleanup, alignment, mixing, mastering and governed local export**. Generated SFX is explicitly excluded and remains a later provider gate.
- Independent verification found the corrected title and `runtime_verified` maturity at direct Backend HTTP `200`, with the public Nginx capability path still intentionally `404`. Alembic remained `0034`, all queues were zero, readiness passed `30/30`, non-Backend service identities were unchanged, critical-log hits were zero and provider activity remained `0 / $0.00`.
- Because the protected correction was already active and Healthy when observed, no duplicate restart or deployment was performed by this closeout flow.
- Sanitized observed-activation evidence: `.deployment-backups/phase36g-stage2-truth-boundary-activation/phase36g-stage2-truth-boundary-observed-activation.json`, SHA-256 `65a699eb93d8491029b9684382c2adf6637f6d7df76847b239676aa0e2d48e10`.

## Next safe gate — Stage 3

Stage 3 may evaluate one separately bounded STT or stock-voice TTS route only after free preflight, official pricing/cost cap, exact operation-specific runtime evidence and explicit operator approval. Music/vocal generation, voice transformation and voice cloning remain later legal/rights/provider gates and must not be bundled into that first provider acceptance.

## Stage 3A — pinned OpenAI stock-voice TTS source and isolated candidate

The Owner explicitly approved proceeding from the Stage 2 safe checkpoint on 2026-08-22. Stage 3A deliberately selects **one stock-voice TTS route only**. It does not bundle STT, dubbing, multi-speaker speech, music, generated SFX, custom voices, voice transformation or voice cloning.

### Official route and free credential/model preflight

- Provider/model: OpenAI `gpt-4o-mini-tts-2025-12-15`, pinned snapshot only.
- Provider operation: `POST /v1/audio/speech`, stock voice. The corrected transport requests the provider’s documented raw 24 kHz signed 16-bit mono PCM, validates duration from the actual byte count, and wraps a canonical finite-length WAV locally before durable completion.
- Initial accepted voice set is restricted to provider built-in stock voices; the first canary is planned for `marin`. No voice sample, custom voice ID, cloned identity or rights claim is accepted by this route.
- Official pricing evidence recorded for the gate is `$0.60 / 1M` text-input tokens and `$12.00 / 1M` audio-output tokens. The synchronous Speech endpoint does not return exact per-request usage/cost in the current contract, so the durable execution must retain `actual_cost_usd=null` unless the provider later returns authoritative usage. The bounded gate is therefore expressed truthfully as one request, a short input, a maximum output duration and a conservative `$0.05` operator cap — never as fabricated exact billing.
- Credential-specific free model lookup returned HTTP `200` and exact model ID match. Total free lookup requests were `2`; billable speech-generation requests remained `0`, provider spend remained `$0.00`, and no credential/header was retained. Sanitized preflight SHA-256: `9c2ea19a39c4ad1fd3aab731012acbfe14a2132000082e5e8edb79fefbaa809a`.

### Source-first execution authority

Stage 3A adds Alembic `20260822_0035` and one tenant-scoped `audio_speech_executions` authority rather than reusing the generic project runner or inventing a second media store. The authority records:

- explicit `planned -> queued` arm before provider spend;
- exact Owner-approved maximum cost matching the durable cap;
- one pinned provider/model/operation and built-in stock voice;
- input and instruction SHA-256 plus character count, while the public snapshot returns no source text;
- bounded attempts, lease owner/expiry and fencing token;
- durable `provider_state=not_started -> submitting` **before HTTP**;
- provider request identity only in protected persistence, exposed publicly as a boolean/hash rather than raw ID;
- sanitized provider/usage metadata, output checksum/size/duration and truthful unknown-vs-known actual cost.

The Speech endpoint is synchronous and exposes no durable provider job ID that can be reconciled after an uncertain network outcome. Consequently an expired lease in `submitting` is marked `ambiguous/failed`; automatic resubmission is forbidden. Only a definitive pre-creation response such as HTTP `429` can be considered safe for a bounded retry, and the first live canary remains `max_attempts=1` regardless.

### Provider speech plus accepted local audio chain

A governed `speech` or `narration` plan compiles to:

`pinned stock speech -> local cleanup -> local mastering -> waveform -> governed final export`

The provider node has no FFmpeg render step. After provider PCM is validated and wrapped into a canonical governed WAV, the already Production-accepted Media Worker performs cleanup, `-16 LUFS` mastering, `36G.audio-qa.v1`, a real PNG waveform and the selected final WAV/AAC/Opus export. Music and generated SFX are rejected before graph creation. The pipeline requires one stock voice/speaker, zero source audio and no voice transformation/clone path.

A permanent `audio-speech-worker` service is included under the explicit `audio-execution` Compose profile, non-root, all Linux capabilities dropped, `no-new-privileges`, and `AUDIO_SPEECH_LIVE_ENABLED=false`. Production deployment must start in this disabled state; live acceptance will use a separate one-shot execution while the persistent worker stays hard-disabled.

### Isolated verification completed

- provider transport and disabled/live worker contracts: `20/20 PASS` under `--network none`;
- AudioFactory inventory/planning regression: `12/12 PASS`;
- durable authority/pipeline/Studio/local-media tests: `12/12 PASS`;
- affected Audio/Media/Video regression on disposable PostgreSQL 16 + Redis 7: `58/58 PASS`;
- Alembic clean round-trip `0035 -> 0034 -> 0035`: PASS; the table appeared, disappeared and reappeared exactly, with PostgreSQL critical hits `0`. Evidence SHA-256 `104ee589361b71291edba849b16aa69bb42ae59e4e42f7cbbacd416cf169ae9c`;
- complete AIOS Core suite: `761/761 PASS` in `31.99s`;
- complete Backend on fresh writable source + PostgreSQL 16 + Redis 7: **`841 passed, 2 warnings, 0 failed`** in `308.05s`, coverage `65.21%`, database/cache critical hits `0/0`;
- complete Backend log SHA-256 `d145403decbbf4c3fde866ccf05e396dad8b081648d7ac5c4dcd136128ab4c62`; metadata SHA-256 `d9a1b6d1a0f8d02caa11fd9c8861ca958bdc6baae6725bed8f968b112b2582a5`;
- full Backend Ruff PASS and Mypy PASS across `212` source files;
- both Production Compose manifests and workflow YAML: PASS;
- real current-source Backend runtime image `sha256:90b0830de52c03054e50585c786be174efc0895d4df0662c09112f13fc4bd65e` passed the stock-speech disabled smoke under `--network none` with cycles/errors `0/0`, no credential read and zero provider requests/spend;
- runtime-image build log SHA-256 `9b628466596b7fdef07891be2d8d3faf27d51726e6187f3d5baeb6be9174bc65`; offline-worker evidence SHA-256 `0e02ef2469f82e7978240d95d74f40b19337415f7c2ba98c23c5660a58fe59fa`;
- fresh Backend test image `sha256:6ca8d1404fe016b931dca22c97f0e5c0fd84d74e53f5d7f9770e79b4d97715d4`; build-log SHA-256 `77101cce4430c21991ee47ae8d9db195e010dab93812b5751a3815aed590ac2a`.

No Production source, service, schema or data row was changed by this source work. Billable TTS requests and provider spend remain `0 / $0.00`.

## P36-0023 — first free model preflight wrote to a host-only path inside the container

- The first free authenticated `GET /v1/models/{model}` reached its HTTP step, but the wrapper then attempted to create the evidence file at a host path that was not mounted inside the Backend container.
- No speech generation endpoint was called; billable generation requests, database writes, service restarts and provider spend all remained zero. No credential or authorization header was returned.
- The corrected wrapper emits sanitized JSON to stdout and redirects it into a mode-`0600` Host evidence file. The free model lookup was repeated once, so the truthful free-preflight request count is `2`.
- Permanent rule: container probes may write only mounted paths or stdout; host-only evidence paths are forbidden inside containers.
- Sanitized incident evidence SHA-256: `796be2b1f7e596a0c735e146cd49c790104da32ddd9a2c6ca7ff87fc1cdb3c16`.



## P36-0024 — disposable PostgreSQL readiness probe raced database creation

- The first migration round-trip did complete `0035 -> 0034 -> 0035`, but the broad log gate found one `FATAL: database "aionex_test" does not exist` emitted while the official PostgreSQL image was still creating the requested `POSTGRES_DB`.
- This occurred in a disposable test container before application migration traffic. Production was untouched, the final database/table state was correct, and no provider request or spend occurred.
- The retained round-trip waits for the image's `PostgreSQL init process complete` marker before the first database-specific readiness probe. The clean rerun passed with critical hits `0`.

## P36-0025 — first full Backend run retained a stale exact Compose image count

- The first complete Backend run reached `840 passed` and failed one static deployment contract because adding `audio-speech-worker` increased the number of `aionex-aios-backend:local` services by one in each Production Compose manifest.
- Runtime logic, migration, provider transport and database tests did not fail. The contract was updated from `11/10` to `12/11` and now also asserts the new worker profile, command, non-root user, `live=false`, dropped capabilities and `no-new-privileges` boundary.
- The focused contract passed, and the retained complete rerun finished `841/841 PASS` with the same `65.21%` coverage and zero database/cache critical hits.

## P36-0027 — streamed provider WAV exposed an indeterminate duration header

- Protected PR #467 merged as `2cafe0243a81e51c6502655fd33bf93eb57c8b90`. A pre-`0035` PostgreSQL dump/restore passed, Production migrated `0034 -> 0035`, Backend was recreated and the new permanent Audio Speech Worker started hard-disabled with cycles/errors `0/0`; all non-target services remained unchanged and provider activity stayed zero during deployment.
- The first real one-shot used the pinned model, built-in `marin` voice, a short synthetic input, `max_attempts=1`, a `20s` duration cap and a `$0.05` approved upper bound. Exactly one provider HTTP invocation occurred. The provider response passed RIFF/WAVE parsing but its streamed header reported a duration outside the strict cap, so the adapter rejected it as `provider_audio_duration` before object storage, Media execution or Studio revision.
- Exact provider billing was not returned and is therefore not fabricated; `actual_cost_usd` remains unknown and the approved upper bound is `$0.05`. No provider request ID or output object was committed. The failed synthetic scope was checkpointed, then deleted; Audio/Media active counts returned to zero and the permanent worker remained disabled.
- The correction does not weaken the duration gate. It requests the provider’s documented headerless PCM contract (`24 kHz`, signed `16-bit`, mono), derives duration from the actual byte length, and only then wraps those validated samples into a canonical finite WAV. This avoids trusting a streaming RIFF length placeholder while preserving the same governed WAV/local-mastering contract.
- Regression coverage requires the exact provider payload to request `pcm`, rejects odd/truncated or over-duration PCM before completion, and proves the local wrapper emits a finite WAV accepted by the existing WAV inspector. The correction passed provider/worker tests `22/22`, disposable PostgreSQL/Redis Audio regression `44/44` with critical hits `0/0`, complete Core `761/761`, and complete Backend `842 passed, 1 skipped, 2 warnings, 0 failed` with `65.10%` coverage and database/cache critical hits `0/0`. Retained Backend log SHA-256 `998bfcb7e937177545d3ef8f6c16cff8c16b152803920a557d9e2c4d7387c4e2`; metadata SHA-256 `30db43901919b7aa60db26d2596c050d87a5b6b5b6c9feaddd698d3750a228bc`. No second live request is permitted until this correction passes protected CI and is deployed disabled.
- Sanitized failed-canary evidence SHA-256: `1d8ab0fe00f38dc370f9b2590924d823f409c611e18f674aaf650c19fbcce673`; cleanup/incident evidence SHA-256: `0594a12676d82adb72dfd48d3e003280820fd01ce21c1103fd47e94b9872c859`.

## Stage 3B — corrected PCM transport and live Production acceptance

- Protected PR #468 passed every required gate and merged as `887ec9f289bab85b1794514c6a33763d69f69b62`. Alembic stayed `20260822_0035`; the prior Backend image `7a45406a...` was retained as `aionex-aios-backend:rollback-phase36g-stage3-pcm-20260822T125832Z`, while Backend and the permanently hard-disabled Audio Speech Worker alone moved to image `sha256:fc3f1aa90e47a9fe7e0033520eec8db04ac0b7fa03b04e374973c4a2036c6c54`. Studio, Media, PostgreSQL, Redis, Image, Derivative, Video, Frontend, Portal and Nginx identities remained unchanged. Offline PCM-to-canonical-WAV smoke and read-only Production preflight both passed with zero provider requests/spend. Consolidated PCM activation evidence SHA-256: `a449eb3314b0aad84ab9a5dba2944a9b8efe34b3f7a56340daaac8153be7faab`.
- The final pre-canary gate proved Alembic `0035`, `audio_speech_executions=0`, every active queue zero, one persistent Audio Speech Worker only, `live_enabled=false`, cycles/errors `0/0`, and direct Backend readiness `200`. Pre-canary evidence SHA-256: `ee4102c6263da6dd937bacf520133e59f48bdcebbb9887a40fd25029c27cb153`.
- One new separately armed execution used pinned `gpt-4o-mini-tts-2025-12-15`, built-in `marin`, a 65-character synthetic input, `max_attempts=1`, a `20s` duration cap and the same `$0.05` approved upper bound. It made exactly one provider audio request. The provider returned validated 24 kHz signed 16-bit mono PCM, which was wrapped into a finite `271,244`-byte WAV (`5.65s`, SHA-256 `8367e159a016595254782aa1bb955a78da00271353ca24e13cc00293db80b460`). No duplicate submission occurred.
- The existing persistent Media Worker completed cleanup, mastering, waveform and final export. The governed output was a `1,084,878`-byte 48 kHz stereo PCM WAV (`5.65s`, SHA-256 `af5af55282ce9f04980f09ed34467f868451a1784881fa1469b716c1c566db52`); the PNG waveform was `6,047` bytes, SHA-256 `d92d2678bcfa40b594b9eb26a452e5726bbf161eb7568d172d3ca26559af34bd`. Master/export passed `36G.audio-qa.v1` at `-16.61 / -16.77 LUFS`, and Studio advanced exactly `1 -> 2`.
- A validated-before-cleanup checkpoint was written first. Cleanup then deleted and independently verified missing `5/5` objects, removed every synthetic Organization/User/Studio/Media/AudioSpeech row, returned `audio_speech_executions=0` and every queue to zero, and removed the one-shot container. The persistent worker stayed `disabled`, cycles/errors `0/0`; readiness passed `30/30`, public/portal returned `200/200`, Owner stayed protected by `302`, and Backend/Media/Audio/Studio critical-log hits were `0/0/0/0`.
- Exact provider usage/billing was not returned, so `actual_cost_usd` truthfully remains `null`. The successful request is bounded only by its approved `$0.05` upper limit. Checkpoint SHA-256: `2916e882f90767a5162115e7028c838de8a53c9720274fcb611d74106a754f48`; live-result SHA-256: `7364676ec6a187c2ad0098610ff1849d817b533451832c3a75f76d72fb0d17a`; corrected consolidated acceptance SHA-256: `0cdbf4baafda5d16938fb6eb473ab6064befc8a3cbe933e3b394dbb471986ebf`.

## Stage 3 total provider accounting

Stage 3 crossed the provider audio boundary exactly twice: the P36-0027 response rejected before storage and the later successful PCM acceptance. Each execution used `max_attempts=1`; there were no automatic retries or duplicate submissions. Exact cost is unavailable for both requests and is not fabricated. The combined approved upper bound is therefore `$0.10`, not a claimed bill. Aggregate provider-accounting evidence SHA-256: `63990878badaea35e3bdf0c4bcb405c85cac2f4efb393bd8f969872efc080623`.

## P36-0026 — root-only canary script was unreadable to the non-root one-shot

- The first wrapper for the corrected canary mounted a root-owned mode-`0600` script into a service that runs as UID `1000`; Python never opened the script.
- No application code ran, no row was created, and the provider boundary was not crossed. Audio/Media remained zero and the permanent worker stayed disabled with cycles/errors `0/0`.
- The corrected wrapper mounted a dedicated UID-1000 read-only script file and a separate writable evidence directory. Incident evidence SHA-256: `3f8daf5f703a35bb4dfee0cfbc5f7b13ace3ddfe79ae1a58fabfbed24b6af30f`.

## P36-0028 — first consolidated acceptance wrapper hard-coded the pre-correction commit

- Immutable precheck, checkpoint and live-result files all recorded the correct PR #468 source `887ec9f...`, and both running containers exposed the PCM transport. The first host consolidation wrapper nevertheless wrote literal `2cafe024...` metadata.
- No provider request, service restart, schema change or data mutation occurred during correction. The original file was retained by hash and the consolidated evidence was rebuilt from immutable inputs. Incident evidence SHA-256: `eb0386c81f966f93b344aba123a56776648488824409afb691655aefe92fb3fb`.

## Stage 3 maturity decision

Only the newly split `stock-voice-tts` capability advances to `runtime_verified`, with a mandatory `synthetic-voice-disclosure` gate. This claim is bounded to the pinned built-in stock voice, provider PCM validation, canonical WAV wrapping, the accepted local cleanup/mastering/export chain, Studio materialization and complete cleanup evidence.

The broader `stt-tts-dubbing` capability remains `source_built`: no provider STT or complete dubbing execution has been accepted. `podcast-jingle-narration` remains `source_built`; `song-production` and `voice-transformation` remain `specified`; generated SFX, custom voices, voice transformation and voice cloning remain outside the Stage 3 claim. Phase 36G remains `in_progress`.

## Stage 4A — governed single-speaker STT, captions and dubbing contracts

Stage 4A deliberately separates one narrow single-speaker STT runtime from broader diarization and dubbing claims. The launch candidate pins OpenAI `gpt-4o-mini-transcribe-2025-12-15`, accepts only a checksum-verified finite PCM WAV (`audio/wav` or `audio/x-wav`), limits the source to `20 MiB / 10 minutes`, uses `response_format=json`, and permits exactly one attempt after an exact Owner cost-cap arm.

The official pricing record is preserved as an **estimated** `$0.003 / audio minute`, alongside `$1.25 / 1M` audio-input tokens and `$5.00 / 1M` text-output tokens. The endpoint does not provide authoritative per-request usage in the accepted contract, so `actual_cost_usd` remains `null` unless provider usage evidence is returned; the durable record stores the estimated duration cost and separately approved maximum.

New provider-neutral contracts add:

- hash-bound governed source evidence with no public storage locator;
- private transcript documents and hash-only public snapshots;
- pseudonymous `speaker-NNN` keys rather than real speaker identities;
- deterministic WebVTT/SRT plus a hash-only caption manifest;
- a provider-neutral dubbing plan that preserves segment timing and speaker scope but remains blocked on translation evidence, per-segment stock TTS, timing fit/alignment, and final local mastering.

Alembic `20260822_0036` adds tenant-scoped `audio_transcript_executions` with arm-before-request, source checksum/size/duration/rate/channel evidence, one-attempt budget, lease/fencing, durable `provider_state=submitting` before HTTP, ambiguity-to-`needs_review`, private transcript package metadata, Studio revision evidence, and hash-only public output fields. An expired lease before submission may be reclaimed without consuming an attempt; an expired `submitting` lease is never resubmitted automatically.

The `audio-transcript-worker` is profile-gated under `audio-execution`, non-root, capability-dropped, `no-new-privileges`, and hard-disabled by `AUDIO_TRANSCRIPT_LIVE_ENABLED=false`. The Worker validates source size, SHA-256, finite PCM WAV duration/sample-rate/channel evidence **before reading a provider credential**, then revalidates the same envelope inside the exact transport.

The new granular registry claim is `governed-stt-transcript=source_built` with external gate `provider-transcription-runtime-evidence`. No STT maturity advance, provider request, credential read, Production migration, service restart, or provider spend is claimed by this source checkpoint.

### Stage 4A isolated verification completed

- Authenticated free model lookup for `gpt-4o-mini-transcribe-2025-12-15` returned HTTP `200` with an exact model-ID match. It made one free metadata request, zero transcription requests, and `$0.00` provider spend; sanitized evidence SHA-256 `c73a19dfbad6b25aef52360da9207c08bdb23df1f6eacec34dac19108489f6ba`.
- Root transcript/AudioFactory/governance contracts passed `35/35`; complete AIOS Core passed `771/771` in `30.40s`. Core log SHA-256 `1285ac77614f9581cfef607b0cc2f1368131f94af6f445a44d3933d30987e79e`; metadata SHA-256 `23e52f4bba79a1f493851c2b7bb5befb03036b0b33cf4c46d8d12fb55a94fcbb`.
- Provider/Worker/Compose/registry/head contracts passed `26/26`; durable transcript authority passed `27/27`; affected Audio/Media regression passed `89/89` with PostgreSQL/Redis critical hits `0/0`. Affected-regression log SHA-256 `2cdea5adec209dfe5ec8545324f9c676bb979e6a25fbc0102811395e367aa607`; metadata SHA-256 `0a34f1fb0490ce3811afe588212f73568046dc073c4a42a8fceba5af44ddef32`.
- Alembic clean round-trip `0036 -> 0035 -> 0036` proved the transcript table appeared, disappeared, and reappeared with row count zero and PostgreSQL critical hits `0`; evidence SHA-256 `11ebac8a67fb3517be89d30257796face6f302ed858a2d48715f47489aa5492a`.
- Complete Backend validation passed `871 passed, 1 skipped, 2 warnings, 0 failed` in `310.41s` with `65.36%` coverage, full verify script, Ruff, Mypy, PostgreSQL/Redis critical hits `0/0`. Backend log SHA-256 `e7ccb8c2d63500c6571ad975788c64adfa62a57a8d4001716ff1eba1d0e97f1e`; metadata SHA-256 `195df859cd0db4b5dcd1cf6dcd74f43370032f8c870d56d3a148cb22d0729c80`.
- Exact Backend test image `sha256:e66758499d79395b521d58d4d16cd4476937e3d353f0e5147c77a10db940a484` built successfully; build-log SHA-256 `d3a29e97f55336ce4824b668e6c026fb6894ab08a9d6bc915399d0fddfdafff0`.
- Exact Production candidate image `sha256:2fc8df776a3afa3a93266133ce4039dfb96a4feb46d75e17b6a49e78b8785a1a` passed the Worker smoke under `--network none` with `live_enabled=false`, cycles/errors `0/0`, no credential read and zero transcription requests/spend. Build-log SHA-256 `9c540fd99cbeebc0e8363b27d096e3ac4e507bb6635511b0069dc927f269e0be`; offline-smoke SHA-256 `96a7bce71d6cb085974fdd6f0569a79eabd8b00b5cfef3f075bcf51ce27372d8`; candidate metadata SHA-256 `da4b03d76013131bfa76c79dc5696e2c8c6c1d779889ff153bf4ed14477a83f4`.
- Both Production Compose manifests, workflow YAML, focused/full Ruff/Mypy, AST parse, repository secret/security audits, Phase36 reporting and `git diff --check` are required to pass again after the final staged commit. Production remains on Alembic `0035`; no Stage 4 source has been deployed and no transcription request has been sent.

## P36-0029 — Docker evidence probes omitted stdin attachment after successful tests

- The first retained affected-regression run completed `89/89`, but its post-test JSON probes used `python -` without `docker run -i`; the evidence formatter received empty strings and stopped after the tests.
- No code test failed, no Production resource was touched, and provider activity remained zero. The retained rerun attached stdin explicitly, repeated the regression and migration round-trip cleanly, and produced the evidence hashes above. Incident evidence SHA-256 `7520978923461beab1bae8f710a1dd1153b3cc6e8ba6a8b2499505ef0ed84c63`.

## P36-0030 — Core zero-dead gate found a hidden rollback cleanup failure count

- The first complete Core run reached `768 passed` and failed three repository-readiness checks because transcript-package rollback used a bare `pass` when object deletion failed.
- The fix preserves the original exception, counts failed cleanup deletions, and attaches only the sanitized count as an exception note. Focused readiness tests passed `5/5`, then complete Core passed `771/771`. No provider or Production boundary was crossed. Incident evidence SHA-256 `6075c6bafabbaca12f077fd9cddc0d50b40d4558bc28f19a4a9005ec2bb9cbe9`.

## P36-0031 — first candidate Worker smoke omitted the Production source mount

- The Production image built successfully, but the first offline smoke omitted `/workspace/src` and the Compose-equivalent `PYTHONPATH`; import stopped before the Worker ran. The empty artifact was deleted.
- The exact same image was rerun with the Production read-only source mount and passed under `--network none`. No credential, provider request, service restart, schema change, or spend occurred. Incident evidence SHA-256 `cdc3796c1de9810393f3709850b054f8e0a7fa6320bc78601a10a4475f60a79e`.

## Stage 4B — protected disabled deployment and single-speaker STT Production acceptance

- Protected PR #470 passed every required CI gate and merged head `1d2b0f3744f75d110cbc82a36944d89182119823` as `7138a9f4882dc48d219d3a9a8343f6cc27170cfe`. The pre-`0036` dump SHA-256 is `59767090bf9bb0745140e5d9c449b754cd80a55ab03fe38de421fd47bf7647dd`; an actual restore reproduced Alembic `0035`, two organizations, fifteen provider rows and no transcript table, then the temporary database was deleted. Consolidated predeploy evidence SHA-256: `a17a3a55691ed18447f9023a5facf7d71a269960e3580b62b446aec8a8365807`.
- The exact protected source built Backend image `sha256:203a9ed8d4cd51cc0959f1634b5f566988da803c836249d8aa4fcc193d7a0fb2`; its no-network Transcript Worker smoke passed disabled with cycles/errors `0/0`, no credential read and zero transcription requests/spend. Production preflight observed Alembic `0035`, zero active queues and no transcript table without modifying the database.
- Production migrated `0035 -> 0036`; the transcript table appeared with zero rows. Backend alone was recreated on the protected image and the permanent `audio-transcript-worker` was started hard-disabled. Speech, Media, Studio, PostgreSQL, Redis, Image, Video, Frontend, Portal and Nginx identities remained unchanged. Migration evidence SHA-256: `1afbe9793a401c687bf025fe408d6d72f853957980085c0a562f9d533a566a26`; recreation evidence SHA-256: `e3330d0bb40f91009d0e74173d1d7fe383bc90db1b66c53bc034b1b4fed0386d`; disabled Production evidence SHA-256: `9750fd1c9b0002494e478e3e38597a7cea9862e7fa4579761620324355ff1333`.
- A fresh authenticated free model lookup returned HTTP `200` and exact `gpt-4o-mini-transcribe-2025-12-15` identity with zero transcription requests/spend. One local `5.24449s` synthetic PCM WAV was then armed with `max_attempts=1`, estimate `$0.0002622` and exact Owner cap `$0.005`. Exactly one provider transcription request completed; there was no automatic retry or duplicate submission. Actual cost remains truthfully `null` because authoritative per-request usage was not returned.
- The accepted private transcript contains one segment and one pseudonymous speaker, with 64 characters and text SHA-256 `8bf08cd92dcbd71e467f4168e18d588afed487b163ad2286156efd74ffdb22d0`. All three fixture keywords matched. The governed package is `1,503` bytes with SHA-256 `308efb6f8c438ae564736b6c86dd64ce6e19052048eb65b0d6c78ceee5a5295c`, contains the private transcript, WebVTT, SRT and hash-only manifest, and materialized Studio revision `2`.
- A validated-before-cleanup checkpoint was written. Cleanup deleted and independently verified missing `5/5` objects, removed every synthetic Organization/User/Studio/Media/Transcript row, returned transcript total/active and every other active queue to zero, removed all one-shot containers, kept both permanent audio workers disabled, and passed readiness `10/10` with zero critical Backend/Transcript/Media hits. Consolidated Production acceptance evidence SHA-256: `8f26ac69d503f42ac01e1abbb85cc9f6fc44d18adc854d3ee144925746e427e3`.

## P36-0032 and P36-0033 — deployment evidence wrappers failed before mutation

- The first restore post-check lost SQL string quotes inside a nested shell command after a successful restore. The same immutable dump was reused, the restore was repeated and verified, and the temporary database was deleted; Production and provider activity were unchanged. Incident SHA-256: `b45db5b55834b5ae5b6fcf84d0425c3a152596a10b71f23e21357d61db423d0e`.
- The first direct candidate preflight consumed the raw env-file `CORS_ORIGINS` shape instead of the normalized Compose JSON value and stopped before application import or database connection. The empty artifact was removed and the corrected read-only preflight passed. Incident SHA-256: `4377100528b606708e55fc43d7a4fb0c18c009ab24938b5b1405302ddef66f9b`.

## P36-0034 — live validator checked the transcript field name in the caption manifest

- The provider execution, durable transcript package and Studio revision had already completed successfully in one attempt. The host canary then checked `raw_transcript_returned` inside the caption manifest, while the governed caption contract intentionally exposes `raw_caption_text_returned`.
- No retry was permitted or performed. The preserved completed row/package was revalidated by hashes, the correct manifest field, all fixture keywords, WebVTT/SRT content, public redaction and Studio revision. A recovery checkpoint was written before deleting the same existing result. Additional provider requests during recovery were `0`; incident evidence SHA-256: `8fba43170552af88bb6bc66b80c7c930b753c2a900743369e8dd6f6b868bee51`.

## Stage 4 maturity decision

Only the bounded `governed-stt-transcript` slice advances from `source_built` to `runtime_verified`. The claim is restricted to pinned single-speaker STT, a private transcript, pseudonymous `speaker-001`, governed WebVTT/SRT, hash-only public evidence, one-attempt ambiguity safety, Studio materialization and complete cleanup.

The broader `stt-tts-dubbing` capability remains `source_built`; multi-speaker diarization and complete dubbing are not included. `podcast-jingle-narration` remains `source_built`; `song-production` and `voice-transformation` remain `specified`. Phase 36G remains `in_progress`.

## Stage 5A — source-first pseudonymous multi-speaker diarization

Stage 5A reuses the existing `audio_transcript_executions` table, Media DAG, Object Store, Studio revision, arm/cost/lease/fencing and ambiguity authorities. There is no Migration after Alembic `20260822_0036` and no second transcript table.

The launch matrix is explicit and operation-separated:

- single-speaker: `transcribe + gpt-4o-mini-transcribe-2025-12-15 + json`;
- multi-speaker: `diarize + gpt-4o-transcribe-diarize + diarized_json + chunking_strategy=auto`.

Any operation/model/format/chunking mismatch is rejected before HTTP. The diarization route accepts only checksum-verified finite PCM WAV, one attempt, and an exact Owner maximum. The provider’s raw speaker labels and raw segment IDs exist only in the in-memory response. Durable completion remaps first-seen speakers to `speaker-001`, `speaker-002`, etc., creates new local `segment-NNN` IDs, and rejects fewer than two speakers, duplicate provider segment IDs, overlaps, invalid/over-duration timing or timing that collapses after millisecond normalization.

The private package contains pseudonymous timed segments, WebVTT, SRT and a hash-only manifest. Public/Studio/Audit/provider metadata exposes only counts, hashes, timings and pseudonymous keys. Defense-in-depth sanitization deletes raw `speaker`, `speaker_label`, raw-speaker and raw `segments` metadata keys while retaining `speaker_count`, `pseudonymous_speaker_count`, and explicit false redaction booleans.

The new granular capability is `multi-speaker-diarization=source_built` with gate `provider-diarization-runtime-evidence`. The accepted `governed-stt-transcript=runtime_verified` claim remains single-speaker and is not widened.

### Stage 5A isolated verification

- Root AudioFactory/Transcript/Phase36 contracts: `35/35 PASS`; Provider/Worker/registry contracts: `34/34 PASS`.
- Disposable PostgreSQL 16 + Redis 7 affected regression: `84/84 PASS`, Alembic `0036`, transcript rows returned to `0`, critical hits `0/0`, and all disposable resources were removed. Log SHA-256 `6bc3e5ad9e217b3e110ecb27a7fd01e4eedf8e163d257f7790e7f0e2d8e687af`; metadata SHA-256 `805fb664a4b553c5d1234e6d1a8c0507feb231b752744dbcf45a7b1db26c1ff7`.
- Complete AIOS Core: `771/771 PASS`; log SHA-256 `e46b69b36f9d4a50b895c1967e1cad906008c389623ff84106cc82f3d77603a5`, metadata SHA-256 `11cb156f845578fb6cac672b479743c601e10b86ce264ae2ce7c53853ba7720c`.
- Fresh Backend test image `sha256:4c87a9dd749dbb0b9894d556de34a06e9f0861193f3c1cee7c3e454cafdc5725` built from the current source. Complete Backend: `883 passed, 1 skipped, 2 warnings, 0 failed`, coverage `65.47%`, PostgreSQL/Redis critical hits `0/0`; log SHA-256 `60cf378ae23a19f521e2b5db3e52bb40d83012ad49e607420af7d8998e418a15`, metadata SHA-256 `65dcf2a05be4ae0ed3e35bcc96aca24ec29cd5d434d1a6192e08bfd5938fa43a`.
- Full Backend Ruff PASS and Mypy PASS across `216` source files. Exact Runtime image `sha256:87c5287a457d6b15bcd2e20495e45275c212bb8a4df57fc83de78a33cde58694` passed the Transcript Worker smoke under `--network none`: operations `diarize/transcribe` visible, Worker disabled, cycles/errors `0/0`, no credential read, raw-speaker return false and provider requests/spend `0 / $0.00`. Build-log SHA-256 `aff342183608ccd41a0931bafe53931c949337789e80acf9810c7cb458beec87`; smoke SHA-256 `ddce0875c7e31552e941e15e7e60c362a59c4b1a7a0e3954ff2013f9833e5a6b`; candidate evidence SHA-256 `404c5dc465736f242f9a5f16f59f908ba242668b00f2485be80b24a6c8c0bd34`.
- Migration delta is `0`; Production remains on the accepted Stage 4 source/schema with both audio workers hard-disabled, no Stage 5 provider request and `$0.00` Stage 5 spend.

## P36-0037 — raw speaker metadata defense-in-depth

- An isolated completion test intentionally supplied unsafe `raw_speaker_label` and raw `segments` metadata. The current Adapter did not expose these values, but the generic sanitizer would have persisted them if a future Adapter did.
- The sanitizer now treats raw speaker-label and raw-segment keys as sensitive while retaining only safe pseudonymous counts and false redaction flags. The complete PostgreSQL rerun passed `84/84`. Incident evidence SHA-256 `cdc6c6b110fadb65cf2c66977c5f2aaee8a84c58aad14b0a15aca6d91de4ebe0`.

## P36-0038 — literal redaction placeholders entered source assembly

- Test collection found two literal redaction placeholders in the rewritten credential-header function and one lease reset line. Python stopped before application execution, database access or HTTP.
- The original semantics were restored (`credential.strip()`, explicit `raise`, `lease_token=None`), all changed runtime modules compiled, and a focused scan confirmed no placeholder remains in the Stage 5 runtime files. Incident evidence SHA-256 `1ff4f339a14ee71001b4d505b36c1f59d62b1a6cda60a75a52724493b8b05eef`.

## P36-0039 — MCP returned 502 after the full Backend suite had completed

- The long full-suite command finished on the server, wrote evidence, removed PostgreSQL/Redis and the writable source copy, then the MCP return channel emitted HTTP `502`.
- The existing result was inspected and retained; no rerun occurred. It proves `883 passed, 1 skipped`, `65.47%` coverage and zero residual resources. Incident evidence SHA-256 `ec9c174615c78c3e9e79f60add9560cb3ccae701b77a7dd74a3cb89060bb6c18`.

## Stage 5B — protected disabled deployment and live Production acceptance

- Protected PR #472 passed every required gate and merged head `9dcb2e9cef2cb187256820c0c2b0af143cce4f77` as `d490f9a2f098ed17e9e106921ca4d537ea5aac22`. There was no Migration; Alembic remained `20260822_0036`. A rollback tag retained the prior Backend image `sha256:203a9ed8d4cd51cc0959f1634b5f566988da803c836249d8aa4fcc193d7a0fb2`.
- Exact merged source built image `sha256:eaa3484530d60d0ca7f8ff14ba69c0b68fd1ebfdd74c715c559d3a0728b24eb3`. Its no-network Transcript Worker smoke exposed only `transcribe/diarize`, remained disabled with cycles/errors `0/0`, returned no raw speaker labels, read no credential and made zero provider requests. Candidate evidence SHA-256: `2d44ad3671c2c180ce611ff5aeda98fcc43f69ba3dbae6a6be5d67f0cf1141a4`.
- Candidate Production preflight observed Alembic `0036`, zero Transcript rows and every active queue zero, with `live_enabled=false`, no Claim, no credential read and no provider request. Only Backend and the permanent Transcript Worker were recreated; Speech, Media, Studio, PostgreSQL, Redis, Image, Video, Frontend, Portal and Nginx identities remained unchanged. Disabled Production evidence SHA-256: `47f645f3e7b36df4ec1febfce6db3d6ae3ec2fc7fcdec6f7a48f0651649f05e2`.
- A fresh authenticated model lookup returned HTTP `200` and exact `gpt-4o-transcribe-diarize` identity with zero diarization requests/spend. A local `15.999s` two-voice synthetic PCM WAV was then armed with `operation=diarize`, `response_format=diarized_json`, `chunking_strategy=auto`, `max_attempts=1`, estimate `$0.0015999` and exact Owner cap `$0.01`.
- Exactly one provider diarization request completed. Actual cost remains truthfully `null` because authoritative per-request usage was not returned. There was no retry or duplicate submission. The result contained `5` timed segments and exactly two locally pseudonymized speakers: `speaker-001` and `speaker-002`; all five fixture keywords matched.
- The private governed package was `1,922` bytes with SHA-256 `8415998eea382c6f372db08d0e70f52ee065e6663c93a75fa774254883b9d79b`, contained private transcript, WebVTT, SRT and hash-only manifest, and materialized Studio revision `2`. Raw provider speaker labels, raw provider segment IDs, transcript text and storage locators were absent from public/Studio evidence; known-speaker references were not used.
- A validated-before-cleanup checkpoint was written first. Cleanup deleted and independently verified missing `5/5` objects, removed every synthetic Organization/User/Studio/Media/Transcript row, returned Transcript total/active and every active queue to zero, removed the one-shot container, kept both permanent audio workers disabled, and passed readiness `10/10` with zero critical Backend/Transcript hits. Checkpoint SHA-256: `13097526415a45e9ea0f55bb69cdad0d6843ef424168716fe8a8f6c6c779b41b`; live result SHA-256: `ae9317a9e2f40b16d5763a02c77dce2fd1bdcd4a71e3fa3a939de7c51309c1ad`; consolidated acceptance SHA-256: `519fac003f132e8c565c7a503664fdd88429ce58a4328e0cd725f6ad8ba9c7af`.

## P36-0040 through P36-0045 — deployment/canary wrappers stopped safely

- P36-0040: a service-identity template assumed every container had a Health object. Collection was repeated through Docker inspect JSON before any build/restart/request. Evidence SHA-256 `92eb3a2401ca9ade9291746057b44208319512e91bddc06f46994f7fd555035d`.
- P36-0041/P36-0043: build and recreation wrappers changed directory before teeing repository-relative logs. The build and target recreations completed, but no operation was repeated; immutable image IDs, pre/post service identities, DB state and readiness were used instead. Evidence SHA-256 values: `a82ca7f43fae9967dc80bd8535b25aee2ce165a8917a9297447581e0b5e4e108` and `442b25190f5381f91f93003dc699fee5fb3a93259cf58700078d6e0202f78a90`.
- P36-0042: the offline wrapper expected a generic request counter although the successful smoke emitted `provider_transcription_requests=0`; the existing result was validated without rebuilding. Evidence SHA-256 `facb6547dfa2ea0d19bf9d56aa9315555b0dbb2d84f60cb6ebfa75c08d58cf2d`.
- P36-0044: the first pre-boundary DB probe contained a syntax error; it stopped before container creation, DB access, credential read or provider request. Evidence SHA-256 `2e6f5caca235c5ccc74af55522cc90a35221998b9957fd8ae2331b66ab2287c4`.
- P36-0045: final host consolidation used `Path.relative_to` on an already relative path after successful checkpoint, cleanup and post-canary validation. Only the consolidated JSON was rebuilt from immutable hashes; no provider request or service change occurred. Evidence SHA-256 `a8dd9e4f8718819141140dd93d279370243f24fc5841caf0cc12a2d3732e2d3c`.

## Stage 5 maturity decision

Only the bounded `multi-speaker-diarization` slice advances from `source_built` to `runtime_verified`. The claim is restricted to pinned multi-speaker diarization, transient raw provider labels remapped to pseudonymous `speaker-NNN`, private timed transcript, governed WebVTT/SRT, hash-only public evidence, one-attempt ambiguity safety, Studio materialization and complete cleanup.

The broader `stt-tts-dubbing` capability remains `source_built`: translation, per-segment stock speech, timing-fit, alignment, mix/master and final dubbed output have not yet been accepted together. `podcast-jingle-narration` remains `source_built`; `song-production` and `voice-transformation` remain `specified`. Known-speaker identification, voice transformation and voice cloning are outside this claim. Phase 36G remains `in_progress`.

## Stage 6A — source-first complete stock-voice dubbing runtime candidate

Stage 6A composes the already accepted private transcript, pseudonymous speaker, stock-speech, FFmpeg 9 Media DAG, and Studio authorities rather than creating a parallel media system. It introduces one dedicated durable orchestration authority, `audio_dubbing_executions`, through Alembic `20260823_0037`.

The bounded launch route is explicit:

- private segment translation uses OpenAI `gpt-5.6-luna` structured output, preserving one translated segment for every private source segment;
- translation source/target text remains private; public evidence retains only checksums, character counts, languages, segment/speaker counts, cost evidence, and false redaction flags;
- every segment is bound to an already accepted built-in stock voice and a separate `max_attempts=1` speech execution;
- a single aggregate Owner cap must cover the translation cap plus all segment speech caps before the orchestration can be armed;
- custom voices, known-speaker identification, voice transformation, and voice cloning fail closed.

The durable authority records planned/armed/running/submitting/ambiguous/completed state, lease expiry and fencing, one translation attempt, private translation object evidence, per-segment speech pipeline evidence, final Media graph/Studio revision, and truthful actual-cost-known flags. An expired lease before translation submission may be reclaimed without consuming a second attempt; an expired `submitting` lease becomes ambiguous and cannot be automatically resubmitted.

After translation completion, Stage 6 creates one stock-speech pipeline per segment. Shorter speech is padded to the exact source timing window; it is never time-stretched. Speech longer than its source timing window is rejected before final assembly, preserving the completed unaffected segments for selective replacement of the failed segment only. Final assembly reuses local cleanup, alignment, mix, mastering, waveform/export QA, and Studio revision authorities.

The permanent `audio-dubbing-worker` is profile-gated, non-root, capability-dropped, `no-new-privileges`, and hard-disabled by `AUDIO_DUBBING_LIVE_ENABLED=false`. The exact Stage 6 FFmpeg 9 Media Worker is also required at deployment because timing-fit adds governed `apad + atrim` handling inside `audio_align`. Source validation and disabled-worker verification perform no credential read, provider request, or spend.

### Stage 6A isolated verification completed

- Dubbing provider/worker/runtime focused tests passed `30/30` on fresh disposable PostgreSQL 16 and Redis 7; `audio_dubbing_executions` returned to `0`, critical hits were `0/0`, and all resources were removed. Final targeted evidence SHA-256: `f111023b51291eb2acd784f70dc6c4b965c53c4ceca67302b9f12d36d113a63c`.
- The wider Dubbing/Speech/Transcript/Media/Studio regression passed `131/131` with PostgreSQL/Redis critical hits `0/0` and zero provider activity. Evidence SHA-256: `20f27feda373e81c1fde45a9f37ca714270eb972e3ef2606942acb8f5be41265`.
- Alembic round-trip `0037 -> 0036 -> 0037` proved the dubbing table appeared, disappeared, and reappeared with zero rows. Evidence SHA-256: `7917a31b0151dd97aa92c7400d1abd689639505f86fba68782ab66b79697b053`.
- A real FFmpeg 9 `--network none` timing-fit smoke padded a `1.000s` 48 kHz source to exactly `2.000s`, preserved the spoken first second, produced zero-RMS padding, used no time stretch, and allowed no spoken-word truncation. Evidence SHA-256: `87e8a38d5b968cbdf1e2133deb72cbb0c8f857fc87c7320578de2f780a352cb5`.
- Complete AIOS Core passed `771/771`; evidence SHA-256 `97717912dcd19801811bc79231b9c77f677fda7d9c4c100cf711eb34cc0ed6c3`.
- Complete Backend passed `914 passed, 2 warnings, 0 failed` with `65.74%` coverage, Alembic `0037`, zero residual dubbing rows, and independently retained PostgreSQL/Redis logs with critical hits `0/0`. Retained metadata SHA-256: `1fa9f86413c916fb37116ddfcf90b2fb58479790674d962fa0b7828ccae77770`; Backend log SHA-256: `8b72b3148d511903cfa172b82e1c30b237a6f4c10e2bea763af389babef8edad`.
- Final Ruff passed for the changed root files and complete Backend `app/tests`; Mypy passed across `220` Backend source files; Python 3.11 AST parsing passed across all `20` changed Python files. Evidence SHA-256: `42825cc76af95f90cb8e1d1bbfb45e1b7575863f9c8129c1080251ad7fbb236e`.
- Final diff/reporting/security/workflow/Compose/governance/capability gates passed with no Stage 6 redaction placeholder in runtime code. Evidence SHA-256: `92340eef63fb31e9a97dbe3108b8291f8c81c47f4978bb565dde8a7e5c88cc22`.
- Every retained Stage 6 source gate records translation requests `0`, speech requests `0`, provider spend `$0.00`, and `production_modified=false`.

## P36-0047 through P36-0055 — source-validation wrappers stopped safely

- P36-0047 corrected a Core wrapper `PYTHONPATH`; P36-0048 corrected a writable repository-layout assumption for the full Backend suite; neither crossed a provider or Production boundary.
- P36-0049 narrowed the static wrapper from unrelated legacy root files to the complete Backend scope plus exact Stage 6 changed root files.
- P36-0050 proved prior `backend-test` tags had used the default Runtime stage and built the exact Dockerfile `target=test` image instead. P36-0051 used a non-login shell so the image's `/opt/venv/bin` remained visible. P36-0052 supplied the changed-file list from the host because the minimal Test image intentionally contains no Git binary.
- P36-0053/P36-0054 supplied explicit config-only PostgreSQL interpolation values and the existing absolute Production env-file path to validate Worktree Compose manifests without starting services or copying secrets. P36-0055 changed an unreachable capability-test URL from a non-test database name to `aionex_test` after the test safety guard stopped before collection or connection.
- Incident evidence SHA-256 values for P36-0050 through P36-0055 are `1b5c84386497cebb932c1f457479127d128e17e4ca692f348bd5d899c3639642`, `4fe74e07805c8619d96243de3c51d332c72762e33379c4ef5d045cb10265d4`, `bc99e538cb7f98a6d74991bbfd8fc5e147e1f1edcabf546e0fc71f163bc7244b`, `b20ccefbe4dd0e245c24721d78d8956ca5d96f68aff65773bfea25891f43dbec`, `571877e2316364b857b12a58ee610b5ee16ee1d1a83a5ee1687619633205f77a`, and `78bbc133cb7f9e2f148fe54beaeebafdaa66f62de5c2d2234a1e23dc9028bd9d`. None modified Production or crossed a provider boundary.

## Stage 6A maturity decision

Only the granular `complete-stock-voice-dubbing` capability is added at `source_built` with gate `translation-and-segment-speech-runtime-evidence`. No live translation or speech request has been performed for Stage 6, and neither `complete-stock-voice-dubbing` nor the broader `stt-tts-dubbing` capability advances to `runtime_verified` from source evidence.

## Stage 6B — protected disabled Production activation and credential gate

- Protected PR #474 passed every required gate and merged head `8a5bf88f685ce2f16bb5814d2bd1d07c07f90171` as `2937f63f0b38b585e411bc38960d229b229dd9f6`.
- A fresh `11,296,431`-byte PostgreSQL custom-format backup was created and restored into isolated PostgreSQL 16. The restore proved Alembic `20260822_0036`, zero Speech/Transcript rows, and no Dubbing table before migration. Backup/restore evidence SHA-256: `e23d0cbc6d748bcca43d2d532f15fd5569dcb5da66b61b2c9ccd38aeed08b9b8`; dump SHA-256: `f8548b85be6f2b842f4dbf0fe546482fbb71bd091e5c6d9f1c3a9b718155d0ce`.
- Exact merged candidates were built as Backend `sha256:873225af7f532c0bc33dfc5a4bdb0c3e8a63c027320f820194c6f9db163c0fba` and Media Worker `sha256:0c479fdd91045e30dc7dab295d7b130e899c497428c55fb0d2ce8de58042a841`. Network-none disabled Dubbing smoke and real FFmpeg 9 timing-fit smoke passed with zero credentials, requests or spend. Candidate evidence SHA-256: `277b611f51027bc88c3e07c576986212d5980ca38a5b9843331c96e10e35da86`.
- Alembic `20260823_0037` was applied from the exact candidate. Candidate Production DB/Object Storage preflight proved zero Dubbing rows, every audio/media queue zero, no Claim and no credential read. Migration/preflight evidence SHA-256: `f34a761a96380bcaa41b0092f9a841088f495b6603f7f6401a6aaf3fd0d11b39`.
- Backend, the exact FFmpeg 9 Media Worker and the permanent `audio-dubbing-worker` alone were activated. The Dubbing Worker is `healthy/disabled`, `cycles=0`, `errors=0`, stock-voice-only, and returns no transcript, translation or secret. Non-target Production service identities remained unchanged; readiness passed `10/10`; public/portal/owner ingress returned `200/200/302`; all active queues remained zero. Disabled activation evidence SHA-256: `0ff2612a7c4023efd116435bf9c6f00766aac0c08f8ec119d11359b6175c1c71`.
- P36-0065 restored the previously accepted non-secret `AIOS_ALLOWED_HOSTS` and `AIOS_CONTROL_HOST` policy into the mode-`0600` untracked service environment after the first recreated Backend correctly failed closed with `/ready=503`. The corrected Backend is healthy; no provider boundary was crossed.
- A free authenticated lookup then returned `401 invalid_api_key` for both pinned OpenAI translation and stock-speech models. No translation request, speech request, automatic retry or spend occurred. Sanitized diagnostic evidence SHA-256: `a9d04c4bb61f28c35cc72ea6fcfd9d41bb0fbea8751d231d613db126c9d979b6`.
- The granular `complete-stock-voice-dubbing` capability therefore remains `source_built`; `stt-tts-dubbing` remains `source_built`. Final safe-checkpoint SHA-256: `cb97f660916b32fc12e5d003855e1721c41486d53226d279862b695ce239b347`.

## P36-0056 through P36-0068 — deployment and credential wrappers stopped safely

The deployment wrappers failed closed on optional Docker Health fields, the host `python3` name, PostgreSQL initialization handoff, Compose interpolation, hardened image PATH/settings, non-root evidence-file mode, capability snapshot shape, and missing/invalid provider credentials. No stopped wrapper repeated a migration, rebuilt an already accepted candidate unnecessarily, restarted a non-target service, or crossed a provider generation boundary. The only operational correction was P36-0065's restoration of an already approved non-secret host policy.

## Stage 6C — corrected credential binding and complete live acceptance

- The earlier `invalid_api_key` result was traced to the active mode-`0600` service `.env` containing short placeholder values, while the existing Production provider secret file and `.env.production` held valid keys. Only `OPENAI_API_KEY` and `GOOGLE_API_KEY` were atomically synchronized into the active service env with a rollback copy; Backend and Dubbing Worker alone were recreated. Both became Healthy with the authoritative key fingerprints. Key-binding evidence SHA-256: `8bcdf0b6eb38be2d33419ee128c5bcc59675321acf7353bd26e2d95975e5ec5f`; post-recreate evidence SHA-256: `1203428ab8ec37d6ef53cf392bc51c1f29aa91920e45b88f29b1ffad7d860a6c`.
- Free exact model lookups passed for `gpt-5.6-luna`, `gpt-4o-mini-tts-2025-12-15`, `lyria-3-clip-preview`, and `lyria-3-pro-preview` with zero generation requests/spend. Consolidated preflight evidence SHA-256: `945926360b2ffa02ce904965b2250686c122f409394721d95fd0ad3870d14b9c`.
- The bounded live execution used one durable translation request and exactly two one-attempt stock-speech requests under an aggregate `$0.045` cap. Translation actual cost was `$0.0001098`; speech per-request actual cost was not authoritatively returned and remains `null`. No automatic resubmit occurred.
- The accepted output is a `14.5s`, 48 kHz stereo PCM WAV of `2,784,078` bytes with SHA-256 `79a5059ad5287a2a6a286bbb4547871e41500e571a7c97c634f96a10828978dc`. `36G.audio-qa.v1` passed at `-16.03 LUFS`, `-1.03 dBTP`, no clipping; Studio reached revision `2`.
- A stale external validator expected status `translated`, although the accepted worker had atomically advanced the durable result to `speech_running`. The completed translation was preserved and resumed with **zero** additional translation requests; P36-0079 evidence SHA-256: `4e431b136a837c3571678989289369a421a2809dd22d1fe5c045257c09017262`. P36-0077/P36-0078 corrected only non-root script read mode and synthetic ID length before any provider request.
- Checkpoint preceded deletion. Cleanup deleted and verified missing `21/21` objects, removed every synthetic Organization/User/Studio/Media/Speech/Dubbing row, returned all active queues to zero, removed one-shot containers, and passed readiness `20/20`. Consolidated acceptance evidence SHA-256: `9cd9536fe7b756c8d70108e518eb9972f49631b89e681871472f177c90d20d08`.

## Stage 6C maturity decision

Only the granular `complete-stock-voice-dubbing` capability advances to `runtime_verified`. The claim remains bounded to private segment translation, built-in stock voices, exact one-attempt provider boundaries, timing-fit without time stretch/truncation, final local mix/master and complete cleanup. The broader `stt-tts-dubbing` capability remains `source_built`; custom/known-person voices, voice transformation and cloning are excluded.

## Stage 7A — source-first low-cost Lyria music runtime candidate

Google Gemini Lyria 3 is selected as the bounded music route. The default user path is `lyria-3-clip-preview` at the fixed `$0.04` draft price. `lyria-3-pro-preview` at `$0.08` is forbidden until the same user owns a completed governed draft checksum and supplies a separate final-generation approval hash.

The cost policy is enforced before Provider claim:

- one attempt per request and no automatic retry;
- draft-first by default;
- exact request caps `$0.04` draft / `$0.08` final;
- per-user monthly reservation cap `$0.40`;
- at most `10` draft requests and `3` final requests per user per calendar month;
- the same user and same plan reuse the existing execution/output across different idempotency keys instead of buying a duplicate generation;
- a row lock protects the monthly reservation calculation from concurrent overspend.

The `audio_music_executions` authority is introduced by Alembic `20260823_0038`. It persists provider/tier/model, plan/runtime/pricing hashes, rights basis, one-attempt lease/fencing/submission state, fixed cost, MP3 output evidence and ambiguity state. The synchronous Provider boundary persists `submitting` before HTTP; any expired post-submit lease becomes failed/ambiguous and cannot be automatically resubmitted.

The Provider transport is exact to `gemini + generate-music + lyria-3-clip-preview/lyria-3-pro-preview + MP3`. The returned MP3 is size/signature validated and then enters the accepted local FFmpeg path: cleanup, `-14 LUFS` master, waveform and governed WAV/AAC/Opus export. Public snapshots expose hashes and cost policy only; raw prompt, lyrics, Provider text, credential and request ID are withheld.

Rights controls require commercial authorization and Provider terms acceptance, reject named-artist/person imitation language, require original/licensed/public-domain lyric evidence for vocal requests, and make SynthID disclosure mandatory. The current source claim does not assert stems, dedicated SFX, voice identity, voice transformation, clone, or production-ready status for preview models.

### Stage 7A isolated verification completed

- Music/Audio/Phase36 contracts passed `36/36`; Provider/Worker/Compose contracts passed `17/17`.
- Disposable PostgreSQL 16 + Redis 7 focused runtime passed `26/26`, returned `audio_music_executions` to zero, recorded database/cache critical hits `0/0`, music requests `0`, spend `$0.00`; evidence SHA-256 `f2e2fa13c8f81110caef3ddaf226d94727325e9c8be5ff589c622b745e1b6f64`.
- Alembic round-trip `0038 -> 0037 -> 0038` passed with zero rows and zero Provider activity; evidence SHA-256 `11fce9af76f20c29fc62dcdd2102877e058f4435a85c8b56b7badea859361dc5`.
- Complete AIOS Core passed `782/782`; evidence SHA-256 `17c7001f77cc2a5003b6d62de644b25e4e7aa3625a048d788baa715dece22cc9`.
- Complete Backend passed `938 passed, 2 warnings, 0 failed` at `66.03%` coverage, Alembic `0038`, zero residual Music rows, PostgreSQL/Redis critical hits `0/0`; evidence SHA-256 `76974454532a47fda2b59d7167262d9b42b6a8f93f03470704d115a0fb9b264d`.
- Ruff, Mypy across `224` Backend source files, Python AST, Phase36 reporting, workflow YAML, both Production Compose manifests and security audits passed; evidence SHA-256 `cda31709a2d87bcdb97f5f8763e07e7850c2012c0894e1b2165875e5cc0d5999`.
- Every Stage 7 source gate records music generation requests `0`, spend `$0.00`, and `production_modified=false`.

## Stage 7A maturity decision

Only granular `lyria-3-music-generation=source_built` is added with gates `valid-paid-gemini-credential`, `lyria-preview-runtime-evidence`, and `music-rights-and-synthid-disclosure`. No preview model advances to `runtime_verified` or `production_ready` from source evidence.

## Stage 7B — protected merge, disabled Production activation and quota stop

- Protected PR #477 merged head `673c244a9e7a9c702e53063ebb6a68e79fbd5f16` as `092314b8ba05e63809e6c258aac3e80502ec2d7d`. A fresh custom-format PostgreSQL backup was restore-verified before Alembic advanced from `0037` to `0038`.
- Backend and the permanent `audio-music-worker` alone moved to image `sha256:cda3f7e60a3ec9396e87b3f3774e53c3b30eb1f1b812283f01e624ae1fd050f8`. The worker remained hard-disabled with zero cycles/errors, and non-target Production service identities were unchanged. Disabled activation evidence SHA-256: `25222956b4bb28f55ea13c7052cd834b2eec632dc23eb272f4a9ade996e069b6`.
- The authoritative Production Gemini key passed the exact read-only model lookup for `lyria-3-clip-preview` and `lyria-3-pro-preview`, and `countTokens` succeeded without a generation request. Post-deploy preflight evidence SHA-256: `efbf6104da3dcc7d797fe5c7614c580e817d9f437480b66a00a8730b972a7ea6`.
- Three separately invoked, one-attempt `$0.04` Clip acceptance attempts were observed during the bounded live window. Each crossed the synchronous Provider boundary once and ended definitively as `429 RESOURCE_EXHAUSTED / provider_rate_limited`; no automatic retry occurred, no MP3 or downstream rendered output was created, and authoritative actual cost remained `null`. The first two failure evidence SHA-256 values are `71642e3df584356e998fa6c0aa2a878e601d089d05dc53594b03518786c68b54` and `de57af0d8580dfa5d38d81e58c278bf1f926177a31f4e4478555e0f09c8b51cc`.
- The final failed synthetic scope contained one failed Music execution and four unstarted downstream Media steps. Direct database audit proved it was the Stage 7 canary tenant only; cleanup removed its Organization/User/Studio/Media/Music rows, returned Music and Media active queues to zero, touched no Production user scope, and added no Provider request or spend. Cleanup evidence SHA-256: `d2c23b223d60468e7302ae7d46a00702b83beba209db05183f8d760eacce2b64`.
- The existing service-account route obtained an OAuth token, but Vertex `countTokens` stopped at `SERVICE_DISABLED` for `aiplatform.googleapis.com`; the same account lacks Service Usage permission to enable it. The Firebase Web key is explicitly blocked from the Generative Language service. The active Gemini API route remains authenticated and model-visible, so the remaining blocker is generation quota/paid-tier availability rather than key validity. Consolidated external-route evidence SHA-256: `7b41b63a0f652e3ba6dfae8463432d799bedfb367f4578124e467b5aa06c6864`.

## P36-0081 through P36-0083 — Lyria quota and cleanup incidents stopped safely

- **P36-0081:** the first valid one-attempt Clip request returned `provider_rate_limited`; the canary wrote failure evidence and did not retry.
- **P36-0082:** the external canary evidence was strengthened to preserve only sanitized Provider failure code/status/boolean flags and quota metadata; the change itself performed no Provider request.
- **P36-0083:** a later separately invoked Clip attempt left a failed synthetic graph with four planned local steps. It was discovered by direct database audit and deleted only after exact tenant/failure verification; all global Music/Media queues returned to zero.

## Stage 7B maturity decision

`lyria-3-music-generation` remains `source_built`. A valid key, model visibility, hard-disabled durable authority and local FFmpeg path do not constitute runtime acceptance when the Provider has produced no audio. `song-production` remains `specified`; preview Lyria models remain ineligible for `production_ready`.

## Stage 7C — durable same-price Replicate Lyria fallback candidate

The direct Gemini API route remains authenticated but quota-blocked. The selected fallback is Replicate's official Google Lyria models: `google/lyria-3` for the existing internal `lyria-3-clip-preview` draft route and `google/lyria-3-pro` for `lyria-3-pro-preview`. Authenticated read-only probes returned HTTP `200` for the Replicate account and both exact model contracts with zero generation requests/spend. Auth evidence SHA-256: `0c31bf1021034f9883acb8d866bdbf58d237a24504b668fa16491337d607153e`; model-contract evidence SHA-256: `7e069894dd685bfe0ffe5f57b318e2a76c7310d912b4f91b3cff5a1fadcbef7f`.

The fallback does **not** loosen the user cost policy: Clip remains exactly `$0.04`, Pro remains `$0.08`, the monthly reservation ceiling remains `$0.40`, at most `10` drafts / `3` finals are armable per user per calendar month, and `max_attempts=1`. The same user + same plan reuses an existing planned/queued/running/submitted/completed execution even across a different idempotency key. Pro still requires a completed same-user governed Draft checksum plus explicit final approval.

Replicate generation is asynchronous. Stage 7C submits exactly once, persists the Prediction ID durably before any poll, and after that ID exists only polls the same Prediction. Worker restart, transient poll failure, or delayed output cannot create a second paid prediction. Only a pre-ID ambiguous submit may become `ambiguous`, and it is never automatically resubmitted or switched to Gemini. Automatic cross-provider fallback is forbidden after a paid boundary.

The output URL is accepted only from HTTPS `replicate.delivery`; the Replicate bearer token is never sent to the output CDN. Public evidence exposes only the hashed Prediction ID and redacted output metadata. Gemini remains in the general audio inventory for its native STT/TTS/analysis capabilities; Replicate is added only for the Lyria music routes. Named-artist/person imitation remains blocked, SynthID disclosure remains mandatory, and lyric rights remain original/licensed/public-domain only.

Source validation after the safety corrections: Music/Audio/Phase36 contracts `36/36`; no-network Provider/Worker/Compose `23/23`; affected PostgreSQL/Redis `54/54` with zero Music rows; Complete Core `782/782`; Complete Backend `945 passed, 2 warnings` at `66.07%`; Ruff/Mypy (`224` files), AST and diff gates PASS. The two retained PostgreSQL log matches are classified rather than hidden: one expected disposable-server bootstrap shutdown and one expected uniqueness violation exercised by a passing Growth test. No unexpected application database failure was observed. Consolidated Stage 7C source evidence SHA-256: `78349892066e047ff58ebe60a10a99dcbf0ca76731e2a7f6d4db7caec0beea3b`. Provider generation requests/spend remained `0 / $0.00`; Production was not modified by this source candidate.

`lyria-3-music-generation` remains `source_built` until a protected merge, hard-disabled Production activation, fresh free Replicate preflight and one real `$0.04` instrumental Clip produce accepted audio plus local QA/Studio evidence.

## Stage 7D — Stability Stable Audio 2.5 funded fallback candidate

Protected PR #479 merged the durable Replicate fallback as `eabdd3bed520314edcdd9e32c755f5b7bcd53fc5`. A fresh authenticated Replicate preflight proved the account and `google/lyria-3`/`google/lyria-3-pro` model visibility, but the one explicitly bounded Clip prediction attempt returned HTTP `402` **before a Prediction was created**. `prediction_created=false`, output was absent, actual cost remained `null`, there was no retry, and the consolidated checkpoint returned Music/Media/Speech/Transcript/Dubbing active queues to zero with no pending provider cost. Replicate therefore remains a dormant lower-price route until its billing account is funded; it is not retried automatically.

The next already-configured provider is Stability AI. Official Stability documentation records Stable Audio 2.5 text-to-audio at `20` credits per successful generation, `1 credit = $0.01`, failed generations are not charged, output supports MP3/WAV, and the model supports up to three minutes of 44.1 kHz stereo audio. The current Stage 7D route is intentionally narrower: one **30-second instrumental MP3** Draft at `$0.20`, `max_attempts=1`, no automatic retry or cross-provider fallback, no vocal-generation claim, and the existing `$0.40` monthly user ceiling allows at most two successful Stability generations per user per month. Official sources: `https://platform.stability.ai/pricing`, `https://platform.stability.ai/docs/api-reference`, and `https://stability.ai/license`.

Authenticated read-only Stability preflight passed `GET /v1/user/account` and `GET /v1/user/balance` with generation requests/spend `0 / $0.00`. The account had exactly `25` credits (`$0.25`), sufficient for **one** Stable Audio 2.5 acceptance request without an Owner top-up. Preflight evidence SHA-256: `f8ddbdda4ae394e485337166b4df452bc2c28b513a5109c9cb7cc66d0ab7ad3f`.

Stage 7D source reuses the existing Alembic `20260823_0038` `audio_music_executions` authority and the accepted local FFmpeg Media DAG; no Migration or parallel job table is introduced. The granular `stable-audio-instrumental-generation=source_built` capability is separate from Lyria. Rights require explicit commercial authorization, Provider terms acceptance and AI-generated disclosure; named-person/style imitation is rejected. `preview_model=false` and `synthid_disclosure_required=false` are persisted truthfully rather than inheriting Lyria metadata.

Current source verification before protected PR: Stable Audio plan contracts `8/8`; Provider transport `19/19` including exact `$0.20` success accounting, terminal `402/429` without retry, and ambiguous network/5xx without resubmit; Worker contracts `8/8`; disposable PostgreSQL 16 + Redis 7 affected Music regression `40/40`, `audio_music_executions=0`, critical hits `0/0`. The database test proves two `$0.20` reservations reach the retained `$0.40` monthly user ceiling and a third request is rejected before Claim. Focused PostgreSQL/Redis evidence SHA-256: `6f96d56630162f31e2dba040571665b84a238e1043493985a6772adb56cf69dc`. Full Backend then completed `953 passed, 1 skipped, 2 warnings, 0 failed` at `66.05%` coverage with Music rows `0`, PostgreSQL/Redis critical hits `0/0`, and disposable resources removed; Backend evidence SHA-256: `e151414a4e4ab6426f6c2dec9e35d28abf9b030a2aecef157388cc5171be3045`. Core verification accounted for all `790` tests without masking environment differences: the Alpine image passed `783` with seven harness-only legacy failures, then Phase 28 reran `9/9` in a corrected writable namespace and the three OpenSSL-dependent Phase24 tests passed `3/3` on the host executable; consolidated Core evidence SHA-256: `499a5c9ae00a60d1a98dc6bd75e9483843c46478f5ef887cb1ab56710831b01e`. Final Ruff/Backend Mypy across `225` source files, changed-file AST, diff, Phase36 reporting, workflow YAML, repository security and secret-hygiene gates passed; static evidence SHA-256: `eb22c72b09ce39ea7657bfd6586f21c0718dad4ef5468bcf834cf0a78f27752b`. Every Stage 7D source/preflight gate records generation requests `0`, spend `$0.00`, and `production_modified=false`.

## Stage 7D — protected deployment and bounded Production acceptance

- Protected PR #481 passed Backend, Production Docker, Browser, CodeQL Python/JavaScript, SBOM/vulnerability, dependency, reporting and repository-secret gates. Head `029295c34bc1f59347de9d69442deabdf2d86374` merged as `2de1283cc3b3b7350110509ac164cbcad87e1c41`.
- No Migration was introduced; Alembic remained `20260823_0038`. Backend image `sha256:308ea4577ab9c8ea3c194a0db6bf0963d267706be169bfd08e48e7ee38c56c55` passed no-network Disabled smoke and Production DB/Object-Storage preflight before Backend and Music Worker alone were recreated. The prior image remains tagged for rollback; all `26` non-target service identities were unchanged. Disabled activation evidence SHA-256: `98b6b630803dbc91d60eed0e22293705ce32518fa249c97ce0bbb8eb1853d080`.
- The corrected mode-`0600` service environment was verified against the authoritative Production provider file without exposing values. Backend held every authoritative provider binding; Music Worker held the exact Stability/Replicate/OpenAI/Google bindings, stayed `healthy/disabled`, and made zero activation requests. Key/worker evidence SHA-256: `6094f662e576916bd00484a865b4903ce4abd9550452d55274ae4271c1d8b8b1`.
- A fresh read-only Stability account/balance preflight returned `25` credits (`$0.25`) with zero generation/spend. Exactly one `max_attempts=1` Stable Audio 2.5 request was then armed at the explicit `$0.20` cap; no retry and no cross-provider fallback occurred.
- The Provider returned a `496,998`-byte MP3 with SHA-256 `3a81f4d0bebdf4a0ed49c8ac4e75c3d1059ca7ddfd137d527924ae0fc79ddffd`. The persistent FFmpeg 9 Media Worker produced a `30.0s`, 48 kHz stereo PCM WAV of `5,760,078` bytes, SHA-256 `0e0455bee193fd253bbb64a9171cb17d8d6d8a4d6b343ece345b50aff9d35ed7`, plus a real PNG waveform and Studio revision `2`.
- `36G.audio-qa.v1` passed at `-14.46 LUFS`, `-2.29 dBTP`, LRA `13.5 LU`, no clipping. The checkpoint was written before cleanup; cleanup deleted and verified missing `5/5` objects, removed every synthetic Organization/User/Studio/Media/Music row, returned all active queues to zero, removed the one-shot container and passed readiness `10/10`. Final acceptance evidence SHA-256: `b560bdec8a21ac6c13f84855d3e6382001a3b5b91b0d9fbda359ce31663a87b6`.
- Post-acceptance balance was `5` credits (`$0.05`), so the route is runtime-proven but externally funding-gated before another user request. The permanent Music Worker remains hard-disabled and recent Backend/Music/Media critical-log hits were `0/0/0`.

## P36-0089 through P36-0092 — deployment/canary wrappers stopped safely

- P36-0089 replaced a Go template that assumed every Docker container had a Health map; it stopped before image tagging or recreation.
- P36-0090/P36-0091 corrected use of the container name and default development Compose file to the exact Production service/file declared in container labels. Neither stopped invocation recreated a service.
- P36-0092 added an explicit User flush before the synthetic StudioJob. The first canary transaction rolled back at the foreign-key boundary with Provider requests/spend `0 / $0.00` and zero residual rows; rerun was allowed only because no Provider boundary was crossed.

## Stage 7D maturity decision

Only `stable-audio-instrumental-generation` advances to `runtime_verified`. The claim is bounded to a 30-second instrumental Stable Audio 2.5 draft, one paid attempt, exact `$0.20` cap, local FFmpeg cleanup/master/waveform/export, AI-generated disclosure, Studio materialization and complete cleanup. `funded-stability-credential` remains a live external gate because only `5` credits remain. Lyria, broad song production, vocals, stems and dedicated SFX do not advance.

## Next safe gates

1. merge the granular Stage 7D maturity closeout and activate the registry through a Backend-only recreation with zero provider work;
2. keep Lyria direct disabled until Google paid quota is non-zero and keep Replicate disabled until its billing account is funded; never submit both automatically;
3. fund Stability by at least `20` credits before exposing another Stable Audio user request; the current `5` credits are insufficient;
4. complete the universal provider execution matrix so every registered provider is either runtime-accepted on an economic model or explicitly non-routable behind a precise deployment/quota/billing gate;
5. add open-weight image/edit/video candidates only through the existing GPU authority with hard-disabled endpoints, license/model evidence, cost ceilings and real runtime acceptance;
6. full songs with vocals/stems, dedicated SFX, voice transformation and cloning remain separate truth/rights gates.

## P36-0085 — Browser login assertion became ambiguous after passkey support

- Stage/environment: Stage 7D protected PR browser boundary gate; Production untouched.
- Symptom: Playwright `getByRole("button", {name: "Sign in"})` matched both the primary submit button and the existing `Sign in with a passkey` button, causing strict-mode failure while all ten other browser cases passed.
- Root cause: the assertion did not require an exact accessible-name match after the passkey button became part of the live login surface.
- Fix: use `exact: true` for the primary `Sign in` button. No UI, authentication behavior, provider route, schema, service, or Production data changed.
- Regression prevention: login boundary assertions with overlapping accessible names must use exact matching. Provider requests/spend caused by this correction: `0 / $0.00`.

## Stage 7D closeout activation — 2026-08-23

- Protected closeout PR #482 passed every required gate and merged head `c30d34c384db9f642f85a7ef8e1856b0ec3201a5` as `d2dadeb2c6fc59762935bc0b0c6dffe1cb136ceb`.
- Production source advanced by fast-forward only. Backend alone was recreated once on the already accepted image; the image identity stayed unchanged, Music Worker and all other `27` checked services retained their exact identities, and no provider request or spend occurred.
- The live module snapshot and direct Backend HTTP API now both expose `stable-audio-instrumental-generation=runtime_verified` with only `funded-stability-credential` and `music-rights-and-ai-generated-disclosure` remaining. `36G` correctly remains `in_progress`.
- Readiness passed `10/10`. Activation evidence SHA-256: `033d05471fce517e8333ac88a55a0c78916d548de99acb79657a0860fa47e7c4`.
