# Phase 36G — Audio, Voice, Music, Songs & Podcast Factory

Date: 2026-08-21
Updated: 2026-08-22
Status: **IN PROGRESS — Stage 3 pinned stock-voice TTS Production-accepted; STT/dubbing, podcast/jingle, music/vocals and voice transformation/clone remain gated**

## Truth boundary

This checkpoint now separately claims one pinned built-in stock-voice text-to-speech route after protected Production acceptance. It does **not** claim provider STT, complete dubbing, podcasts/jingles, music, vocals, generated SFX, a transformed voice or a cloned voice.

Stage 1 performs no provider request, reads no provider credential and estimates no provider cost. Every generated Studio package remains `provider_neutral`, records `external_requests=0`, `external_cost_usd=0`, `estimated_external_cost_usd=null`, and exposes `render_status=not_started`.

The Phase 36 registry remains truthful:

- `36G=in_progress` and `current_batch=36G`;
- `audio-cleanup-master` and the granular `stock-voice-tts` slice are `runtime_verified`; the broader `stt-tts-dubbing` and `podcast-jingle-narration` capabilities remain `source_built`;
- `voice-transformation` and `song-production` remain `specified`;
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

## Next safe gate — Stage 4 governed STT and dubbing foundation

Stage 4 may build provider-neutral transcript, segment/timestamp, diarization and caption contracts first, then evaluate one separately bounded STT provider/model only after authenticated free preflight, official duration/format/pricing review, one explicit request cap and complete cleanup. Dubbing remains blocked until transcription, translation, per-segment stock speech, alignment and final local mastering each have separate evidence. Music/vocals/SFX and voice transformation/clone remain later legal/provider gates.
