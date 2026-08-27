# Phase 36G — Open Song ACE-Step eager readiness repair

- Receipt ID: 36G-2026-08-27-open-song-eager-init
- Batch: Phase 36G / Open Song live acceptance repair
- Date/time UTC: 2026-08-27
- Objective: Repair the RunPod Open Song handler after the first diagnostic image passed cache/startup but failed at `acestep_generation_failed`.
- Production gap before change: The handler treated any non-empty ACE-Step `/health` response as ready, while the installed ACE-Step API can return HTTP 200 with `models_initialized=false` and/or `llm_initialized=false`. The handler also set obsolete `ACESTEP_LLM_BACKEND` instead of the installed runtime's `ACESTEP_LM_BACKEND` contract, and did not force the current eager-init switches.
- Changed paths/services/schemas: `infra/runpod/open_song/handler.py`, `infra/runpod/open_song/Dockerfile`, `tests/test_phase36g_open_song_handler.py`, and this receipt. Runtime target is the isolated RunPod Open Song endpoint only; production audio worker remains live-disabled during acceptance.
- Technology/version review and official sources: Validated against the ACE-Step 1.5 source baked in the pinned runtime image. The installed runtime consumes `ACESTEP_NO_INIT`, `ACESTEP_INIT_LLM`, and `ACESTEP_LM_BACKEND`; A40/A6000 48 GB class supports the pinned `acestep-5Hz-lm-4B` according to the baked GPU tier table.
- Security/privacy/cost/sector review: No credential values are logged or committed. ACE-Step remains localhost-only, model artifacts remain root-owned/read-only, the handler remains non-root, automatic provider retry remains disabled, and live acceptance retains a single-submission spend cap of USD 0.20. RunPod balance is read live through the existing credential without returning the credential.
- Tests and exact pass counts: `tests/test_phase36g_open_song_handler.py tests/test_phase36g_open_song_factory.py` = 30 passed. Docker source-contract build PASS. Full runtime image build PASS from pinned cached layers. Image runtime checks confirm non-root UID, writable ACE-Step cache, and `ACESTEP_LM_BACKEND=pt`, `ACESTEP_NO_INIT=false`, `ACESTEP_INIT_LLM=true`.
- Performance/load evidence: No load expansion in this repair. Endpoint remains `workersMin=0`, `workersMax=1`, one GPU, A40/A6000 pool, and one acceptance submission maximum.
- Problems discovered: (1) health readiness accepted an uninitialized model service; (2) obsolete backend environment variable name; (3) current ACE-Step defaults can lazy-load unless the current eager-init contract is set.
- Root causes and why prior safeguards missed them: Prior tests validated handler contract, supply chain, cache permissions, and failure-stage sanitization, but did not assert the exact wrapped ACE-Step health payload or current environment variable names from the pinned ACE-Step API implementation.
- Fixes and regression tests: Added strict wrapped health parsing requiring the exact initialized DiT and 4B LM pair; switched to `ACESTEP_LM_BACKEND`; forced `ACESTEP_NO_INIT=false` and `ACESTEP_INIT_LLM=true`; added regression coverage for false readiness, model drift, LM drift, and obsolete environment names.
- PR / merge SHA / protected checks: Commit `6f8f2d6`; PR #525 opened. Merge and final protected-check result pending live acceptance.
- Backup / deployment / rollback: Candidate image `ipdomx/aionex-open-song@sha256:2927309bdb0829197bd20d07caf36ba7eae137f704e090bd3cd8bdc60e81defd`; candidate endpoint created separately before retiring the previous failed endpoint. Production audio worker remains live-disabled. Evidence root: `.deployment-backups/phase36g-open-song-eager-init-live/20260827T150511Z`.
- Live acceptance and before/after metrics: Before repair, one real provider submission failed with `open_song_handler_failed:acestep_generation_failed`, attempts=1, retried=0, and DB residue=0. New-image acceptance is pending in this receipt revision and will be updated before merge.
- External activation gates remaining: Second RunPod account cannot be armed until an independent secondary API key/endpoint is actually configured; no key is fabricated or copied from the primary account.
- Next action: Complete fresh SBOM, activate the candidate binding with production worker still disabled, run exactly one governed Full Song acceptance, record stems/master/export result and cleanup, then update this receipt and merge only with green protected checks.

## Live acceptance v5 finding — required shared ACE-Step components

- The fresh candidate SBOM completed successfully as CycloneDX 1.7 with `12196` components; SHA-256 `50d5e4daf2ed7b6e8558315ef444f8f6ce58f25a5ef96de25ac650d1735b12d9`.
- The production audio-song worker was recreated alone, returned Healthy, remained `AUDIO_SONG_LIVE_ENABLED=false`, and read the candidate Endpoint hash, image digest `sha256:2927309bdb0829197bd20d07caf36ba7eae137f704e090bd3cd8bdc60e81defd`, handler SHA and fresh SBOM SHA exactly.
- Acceptance v5 made exactly one RunPod submission. Terminal evidence: `attempts=1`, `retried=0`, `open_song_handler_failed:acestep_api_startup_exit`; RunPod failed jobs became `1`, with no second submission. The live balance before submission was `$9.9588565024`. Synthetic cleanup returned Organization/AudioSongExecution/MediaGraph rows to zero.
- Root cause is now narrower than the earlier cache/readiness findings. The handler image baked the selected `acestep-v15-base` DiT and `acestep-5Hz-lm-4B`, but did not bake the official VAE and `Qwen3-Embedding-0.6B` text encoder from the ACE-Step main model bundle. Eager initialization therefore exposed the missing shared-model prerequisite before generation.
- The pinned ACE-Step 1.5 generic precheck additionally requires the unused default Turbo DiT and 1.7B LM whenever any main-model component is absent. That contract is broader than this selected Base + 4B runtime and would force a runtime network download, which AIONEX intentionally forbids.
- Remediation pins `ACE-Step/Ace-Step1.5` revision `19671f406d603126926c1b7e2adc169acbcade22`, bakes only `vae/*` and `Qwen3-Embedding-0.6B/*`, and applies a build-time patch only after verifying upstream `init_service_downloads.py` SHA-256 `02a95f2293dc0cd82ff5046816503668f8339157ba0b18715e061f3142999f8f`. The patch makes the precheck fail closed on the selected DiT plus actually required VAE/text encoder instead of downloading unused defaults.
- Regression coverage remains one-attempt/no-retry and adds exact main-model revision, shared-component and upstream-patch assertions. Focused Open Song tests after the remediation are `30/30 PASS`; a new immutable runtime image/live acceptance remains required before merge.
- Owner directive: the secondary RunPod account/failover activation is explicitly deferred until all other project work is complete. No primary key may be copied into the secondary binding; this is not an internal completion blocker for the primary Full Song repair.

## Shared-component image candidate — offline verification

- Full runtime build completed successfully as local image `sha256:d5457ad92cf6a3a926f6bacac75a4adec5b75369f34830fa1b497afc30739c15` (`18,834,408,953` bytes).
- Exact main-model revision is pinned to `ACE-Step/Ace-Step1.5@19671f406d603126926c1b7e2adc169acbcade22`; only the required official VAE and `Qwen3-Embedding-0.6B` shared components are baked in addition to the already pinned Base DiT and 4B LM.
- Real `--network none` image verification PASS: runtime identity `aionex-song` uid/gid `999:999`; official VAE weight `337,431,388` bytes; Qwen text-encoder weight `1,191,586,416` bytes; ACE-Step cache `aionex-song:aionex-song:0700`; checkpoints remain `root:root:0755`.
- Runtime environment remains exact: `ACESTEP_CONFIG_PATH=acestep-v15-base`, `ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-4B`, `ACESTEP_LM_BACKEND=pt`, `ACESTEP_NO_INIT=false`, `ACESTEP_INIT_LLM=true`.
- The patched ACE-Step initialization module contains no `check_main_model_exists`, `ensure_main_model`, or generic main-bundle auto-download path; it still requires the selected DiT and the exact shared VAE/text-encoder components. Runtime network download remains forbidden.
- Handler source SHA-256 remains `a37e47f58940927f53f0393dfc0030d8ecf30363bd4ada23a57d419e37032347`.
- No provider submission occurred during build/offline verification. The next paid boundary remains exactly one new Full Song acceptance after immutable registry push, fresh SBOM and candidate Endpoint readiness.

## Registry-layer optimization before final candidate

- The first shared-component image was functionally correct but combined the already-existing Base DiT + 4B LM with VAE/Qwen in one new `14.8 GB` Docker layer. It was not promoted to a new RunPod candidate.
- The registry push and its in-progress SBOM scan were stopped before candidate creation; no provider submission or Production execution occurred from that image.
- The Dockerfile was split so the historical Base+4B layer is byte-for-byte cache-reused (`9ca71df7c64e`, approximately `13.2 GB`) and only the required VAE/Qwen + verified ACE-Step precheck patch are added in a new layer. The completed build-step writable delta is `1,545,519,104` bytes before Docker layer compression/commit.
- This is a packaging/deployment optimization only: pinned model revisions, strict eager readiness, offline runtime policy, non-root identity, selected Base+4B runtime and VAE/Qwen functional requirements are unchanged.

- Optimized full runtime image completed as local `sha256:d331c97b910ff7be39b1e291bd2b1a7d26438b70ce83065cbb4a4ff9881d5c28` (`18,834,391,023` bytes). Docker history confirms the Base+4B layer `9ca71df7c64e` is reused and the new VAE/Qwen+patch layer is `1.55 GB` uncompressed.
- Network-isolated runtime verification on the optimized image PASS: uid/gid `999:999`, VAE `337,431,388` bytes, Qwen encoder `1,191,586,416` bytes, Base DiT `4,787,825,604` bytes, cache `aionex-song:aionex-song:0700`, checkpoints `root:root:0755`, eager Base+4B environment exact, and patched offline precheck present.
- Focused Open Song tests remain `30/30 PASS`; Phase 36 reporting invariant and `git diff --check` PASS after the layer split.

## Live acceptance v6 — Demucs PyTorch 2.6 compatibility finding

- Candidate `aionex-open-song-70657f5` reached Ready/idle with zero queued or in-progress jobs before acceptance. The production audio-song worker remained `AUDIO_SONG_LIVE_ENABLED=false`; acceptance ran in a separate bounded process and did not change the production live flag.
- Acceptance v6 made exactly one RunPod submission. Terminal evidence: `attempts=1`, `retried=0`, provider failure code `open_song_handler_failed:demucs_separation_failed`; live RunPod balance before submission was `$9.945157258`. Cleanup returned Organization/AudioSongExecution/MediaGraph residue to zero. No second submission was made.
- This result proves the earlier ACE-Step startup/shared-model remediation advanced the real job through eager startup and generation into the Demucs stage.
- Local no-network reproduction isolated the Demucs failure to PyTorch 2.6+ changing `torch.load` to default `weights_only=True`; Demucs 4.0.1's official serialized HTDemucs checkpoint requires the legacy trusted-package loader behavior. The exact upstream `demucs/states.py` SHA-256 is `37375543dad61a7dc549caf6f165c0500d903313159c70cf893d47718194b865`.
- Remediation adds a SHA-gated build-only patch changing only that trusted Demucs callsite to `torch.load(path, 'cpu', weights_only=False)`. The checkpoint remains the official pinned artifact with SHA-256 `8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4`; no global PyTorch override is used.
- The repaired local image is `sha256:f4767c1e1bac23f86d8ddd9d37854cda10c11151c937a346ffb32050bcb57271`. Build-time model load succeeded with patched `demucs.states.py` SHA-256 `cea15bb783d2055f79c637b7e76da84f56e65a6d0f195e54258588ba8142f3e8`.
- A real no-network CPU inference smoke test on the repaired image loaded `HTDemucs` and produced exactly four WAV stems: `vocals`, `drums`, `bass`, and `other`.
- Package-equivalence against the prior candidate is exact: 466 dpkg packages share SHA-256 `934b88589fe13cbcaf7fca36deb392079c4b7604c26744ab990d68b7ea7ae8a7`; 190 Python-distribution inventory rows share SHA-256 `f230cae5eadd0e3e849be47ae5197a92b2340f86988a3197a20d82801c620638`; both diffs are zero bytes. The change is runtime source patching only, not a dependency change.
- A new immutable registry digest/candidate and exactly one subsequent bounded Full Song acceptance are still required before `song-production` can advance to `runtime_verified`.

## Live acceptance v7 — Cloudflare Browser Integrity / urllib finding

- Candidate `aionex-open-song-92ca084` reached Ready/idle with zero queued or in-progress jobs before acceptance. Production `audio-song-worker` remained Healthy and `AUDIO_SONG_LIVE_ENABLED=false`.
- Acceptance v7 made exactly one RunPod submission. Terminal evidence: `attempts=1`, `retried=0`, provider failure code `open_song_handler_failed:artifact_upload_failed`; live RunPod balance before submission was `$9.9132192505`. Cleanup returned Organization/AudioSongExecution/MediaGraph residue to zero. No second submission was made.
- This result proves the real pipeline advanced through ACE-Step eager initialization, Full Song generation, canonicalization and Demucs four-stem separation to the final Artifact Bridge upload boundary.
- Signing-secret parity was verified without disclosure: `audio-song-worker` and `backend` share the same `SECRET_KEY` SHA-256 `e15c32d17b600d0ea3c1e637ac05be8290090b5f4e5a34b58347bcf94838c00f` and both use `https://api.vip-e.net` as the public API origin. Artifact token TTL is the configured 1,800 seconds, so expiry is not the cause.
- An authenticated Artifact Bridge smoke test through the public origin using httpx PASS: PUT `201`, GET `200` with identical body SHA-256, DELETE `204`.
- Reproducing the handler's exact `urllib.request` transport through the same public origin failed with Cloudflare HTTP `403`, Error `1010`, stating that the browser signature was blocked. This isolates the failure before the AIONEX Backend and explains the sanitized RunPod `artifact_upload_failed` result.
- Adding the explicit bounded handler User-Agent `AIONEX-AIOS/OpenSong-ArtifactBridge/1.0` to the same urllib request immediately changed the smoke test to PUT `201` and DELETE `204`. No WAF bypass, Cloudflare policy relaxation, secret change or API route change is required.
- Remediation changes only the Artifact Bridge request header and adds regression coverage forbidding implicit `Python-urllib` transport identity. Focused Open Song tests remain `30/30 PASS`; Phase 36 reporting invariant and source-contract build PASS.
- Repaired local image is `sha256:6b6ce10bda3adc378fff230b307ac1ce9f86aaf21d82cd6e1f9c9b9f2a19ea34`; handler SHA-256 is `15f8b34e8f45ce3f156cd2d0e00df532acd3803e5bdff4370ab670e634652a37`.
- Package-equivalence against the Demucs-fixed predecessor is exact: 466 dpkg packages share SHA-256 `934b88589fe13cbcaf7fca36deb392079c4b7604c26744ab990d68b7ea7ae8a7`; 189 Python-distribution rows share SHA-256 `ccec871935d8c4d49793042a4b14d862940d0fcdb01099e3e57b1c95ba6b0d78`; both diffs are zero bytes.
- Exactly one subsequent governed Full Song acceptance is required. Secondary RunPod account activation remains explicitly deferred and is outside this chapter closure.
