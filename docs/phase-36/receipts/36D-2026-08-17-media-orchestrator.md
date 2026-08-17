# Phase 36D — Universal Creative Asset Graph & Media Orchestrator

Date: 2026-08-17
Status: **IN PROGRESS — final source candidate validated; Production activation pending**

## Baseline

- Phase 36C is protected/merged/activated complete; authoritative `current_batch=36D` on Production.
- Production Studio already has durable `StudioJob`, `StudioAsset`, `StudioAssetRevision`, safety review, project attachment and a lease/retry worker. It currently generates deterministic provider-neutral ZIP/source packages rather than a unified rendered-media DAG.
- Existing 3D runtime already has private S3 storage code, but it is 3D-specific and does not form a general Creative Media storage authority.
- Host FFmpeg is not installed; Phase 36D will therefore use an isolated media-worker runtime rather than depend on host packages.
- Production was not modified by this checkpoint.

## Latest-stable technology review

- FFmpeg target is upgraded from the roadmap's historical `8.1+` floor to **FFmpeg 9.0**, released 2026-08-04. Official source/release index: https://ffmpeg.org/releases/ and https://ffmpeg.org/download.html .
- Python S3 SDK pin moves from `boto3==1.43.67` to **`boto3==1.43.72`**, the current PyPI version resolved on the project host at this checkpoint. Dependency dry-run resolved without conflicts.
- Frontend `sharp==0.35.3` is already current and is retained rather than changed unnecessarily. Official project release source: https://github.com/lovell/sharp/releases .
- Storage architecture is S3-compatible/provider-neutral: local private volume for development/acceptance plus AWS S3, Cloudflare R2 or another compatible endpoint through one adapter. Cloudflare R2's S3 API remains an eligible backend: https://developers.cloudflare.com/r2/api/s3/api/ .

## Foundation implementation

- Added `MediaGraphSpec`, `MediaNodeSpec`, `MediaEdgeSpec` with deterministic canonical checksums and acyclic topological validation.
- Added partial-revision planning: changing one node returns only that node plus downstream dependants, so unrelated scenes/assets are not re-rendered.
- Added initial output-profile registry for lossless PNG, PCM WAV, H.264/AAC MP4 and AV1/Opus WebM. FFmpeg engine target is explicitly `9.0`.
- Added local and S3-compatible private `MediaObjectStore` implementations with SHA-256, size bounds, atomic local writes, path traversal protection, S3 SigV4 and optional custom endpoint URL for R2/MinIO-compatible systems.
- Added Phase 36D persistence models and Alembic revision `20260817_0030`:
  - `media_asset_graphs`
  - `media_asset_nodes`
  - `media_asset_edges`
  - `media_render_steps`
- Existing `StudioAsset` / `StudioAssetRevision` remain the user-facing asset/revision authority; the new graph is an orchestration layer rather than a competing Studio subsystem.
- Added media storage configuration without exposing credentials and retained existing AWS settings as backward-compatible fallback.

## Verification

- Phase36D focused Unit/Domain/Storage/Schema tests: `5/5 PASS`.
- Ruff: PASS.
- Mypy on new media services: PASS.
- `git diff --check`: PASS.
- `boto3==1.43.72` full runtime requirements resolution dry-run: PASS.
- Disposable PostgreSQL 16 migration proof: `0029 -> 0030` PASS, all four media tables present; `0030 -> 0029` PASS with media tables removed; second `0029 -> 0030` PASS. Disposable database removed afterward.

## Remaining before 36D can close

1. Persist/reload complete graph specifications and create render-step plans from existing Studio jobs/assets.
2. Build isolated **FFmpeg 9.0** media-worker image and verify actual binary/version plus software and available hardware-acceleration adapters.
3. Implement resumable render-step claiming, fencing/idempotency, partial retry and stale-lease rejection.
4. Implement deterministic assembly and real output checksum/QA receipts.
5. Integrate final rendered nodes back into `StudioAssetRevision` without breaking Phase29H compatibility.
6. Add provider-adapter boundary so later image/video/audio providers can produce source nodes while FFmpeg remains provider-neutral assembly/transcode authority.
7. Prove local storage and S3-compatible storage contracts; use configured real S3 backend only when credentials/bucket are explicitly available and never fabricate them.
8. Execute the 36D exit gate: create a real rendered asset, revise one scene without redoing unrelated work, reassemble final output and retain provenance/evidence.
9. Only after protected CI, migration backup/restore and production activation evidence may 36D transition to `complete` and 36E begin.

## Safe point

Foundation checkpoint 1 is source-only on `phase36d/media-orchestrator`. No Production schema, container, worker, media provider, object or user data was changed. Production remains on Alembic `0029`, Phase36D `in_progress`.

### 36D PR #419 CI correction — 2026-08-17T19:23:00Z

- Initial protected CI exposed two source-contract regressions only: the repository zero-dead/market-readiness audit rejected a `bare pass` around local media-root permission hardening, and the Backend Alembic-head contract still expected `20260817_0029` after migration `0030` was introduced. No provider, storage, database or Production runtime failure was involved.
- The local object-store constructor now fails closed with sanitized `MediaStorageError` if private-root permissions cannot be hardened instead of silently continuing. The Backend head contract now truthfully expects `20260817_0030`. Focused root zero-dead/market-readiness is `5/5 PASS`; Backend Alembic-head + Phase36D foundation is `6/6 PASS`; Ruff PASS. Production remains untouched on Alembic `0029` pending protected merge/deployment.

## Execution checkpoint 2 — FFmpeg 9 render fabric and Studio integration

- PR #419 foundation merged to `main` as `0d66895e2061fd3bf0d747c3abd6f877912bbd14` after all protected checks passed.
- Added Alembic `20260817_0031` as a forward-only follow-up to merged 0030 rather than rewriting migration history. It adds `lease_owner`, `lease_expires_at`, `fencing_token` and `available_at` to durable render steps plus recovery indexes.
- Added persisted graph runtime: idempotent graph/node/edge/render-step creation, dependency-aware claim scheduling, complete graph reload/snapshot, and partial revision creation that reuses completed unaffected nodes by checksum/storage/provenance and schedules only the changed node plus downstream dependants.
- Added dedicated `media-worker` production target/profile. FFmpeg **9.0** is built from `ffmpeg.org` release source after pinned SHA-256 and official signing-key verification; runtime carries governed H.264/AAC, AV1/Opus, PNG and PCM paths. Project-worker Chromium/Node stages were moved after the media target so Media CI does not build unrelated browser dependencies.
- Added durable Media Render Worker with lease renewal, reclaim, fencing, exponential retry scheduling, stale completion rejection, deterministic output keys, checksum verification, FFprobe evidence and dependency-aware claiming.
- Added Media QA: rendered streams/codecs/dimensions are checked against the governed output profile before a result can be committed. Hardware accelerators are enumerated but non-software activation remains fail-closed unless separately governed.
- Added Studio API bridge: an existing Studio Asset can create/list/get a tenant-scoped media graph, submit partial graph revisions and retrieve final output. Snapshots exclude prompts and storage keys.
- Completed graphs linked to Studio now materialize a real `StudioAssetRevision` and advance `StudioAsset.current_revision` while retaining media graph/storage/engine/QA evidence. Legacy ZIP/source revisions keep the existing protected-root download path; media revisions use their recorded local/S3 backend with checksum verification or private presigned redirect.
- Media storage default is `inherit`: Production reuses the existing governed `STORAGE_TYPE`/S3 credentials when configured, while tests/local acceptance can explicitly use private local storage. No duplicate Media credentials are required when the existing S3 authority is valid.
- Final Validation now has a permanent `Build and verify FFmpeg 9 media worker` gate. It builds the media image and performs real bounded scene renders, final assembly, AV1/WebM, PNG and WAV verification inside the shipped image.

### Verification evidence

- All Phase36D + legacy Studio integration tests: `20/20 PASS` on disposable PostgreSQL 16 at Alembic 0031.
- Broader Backend regression set (36D, Phase29H Studio, Studio frontend contract, route quality/head): `21/21 PASS`.
- Root zero-dead + Market Readiness: `5/5 PASS`.
- Ruff: PASS; Mypy: PASS; Compose production configs: PASS; YAML workflow parse: PASS.
- Migration recovery: `0031 -> 0030` removed all four fencing columns; `0030 -> 0031` restored all four. Disposable database removed afterward.
- Real FFmpeg 9 image smoke: H.264/AAC final MP4, AV1/Opus WebM, PNG and PCM-s16le WAV all rendered and FFprobe-validated. Evidence `/opt/AIOS/.deployment-backups/phase36d-premerge/ffmpeg9-real-render-smoke.json`, SHA-256 `f091ec6faa7df145193dcf6614d1f9c5173bb97745efe2321e2f698daffe0f18`.
- Production remains unmodified at this checkpoint: database still Alembic 0029 and no Media Worker service is activated yet.

### Remaining production gates before 36D closure

1. Protected PR for the execution layer must pass all CI including the permanent FFmpeg 9 real-render gate.
2. Fresh Production backup + isolated restore smoke before schema mutation.
3. Apply merged migrations `0029 -> 0030 -> 0031`, verify rollback anchors/images and existing Studio data.
4. Build/start one Media Worker under `media-execution`; prove FFmpeg 9 health and the inherited real S3-compatible storage preflight without exposing credentials.
5. Run one isolated Production exit-gate project: real two-scene render + final assembly, revise one scene only, prove unaffected-scene reuse, create the new Studio revision, retain provenance/evidence, then remove synthetic canary data/objects.
6. Only after the Production exit gate and post-canary health pass may 36D capabilities move to evidence-backed runtime maturity and Batch 36D transition to `complete` / 36E `in_progress`.

### 36D executable render/runtime checkpoint 2 — FFmpeg 9 + resumable DAG — 2026-08-17T20:25Z

- Foundation PR #419 merged to `main` as `0d66895e2061fd3bf0d747c3abd6f877912bbd14` after all protected checks passed. This checkpoint builds on that merged DAG/storage schema rather than rewriting the Phase29H Studio asset system.
- Latest engine is now reproducibly built as a dedicated `media-worker` Docker target from the official FFmpeg `9.0` source tarball. Build verifies SHA-256 `7f607a00dd0d28a729d5a4811205812eef01cf6ef6155025febb6f36a9062d52`, imports the official FFmpeg release key, verifies fingerprint `FCF986EA15E6E293A5644F10B4322F04D67658D8`, and verifies the detached release signature before compilation. The image includes governed software codecs plus compile-time VAAPI/oneVPL-QSV adapters; hardware use remains fail-closed unless explicitly operator-armed.
- Alembic `20260817_0031` extends render steps with `lease_owner`, `lease_expires_at`, `fencing_token`, and `available_at`. Disposable PostgreSQL proved `0031 -> 0030 -> 0031`; stale workers cannot renew or complete after a lease is reclaimed and fencing generation advances.
- Added durable `MediaRenderWorker`: dependency-aware claim ordering, lease renewal during long render/upload, retry/backoff, exhausted-lease failure, checksum-verified inputs, deterministic fencing-specific output keys, FFprobe QA, storage upload, immutable provenance and stale-completion rejection. Assembly is not claimable until all parent nodes are completed.
- Media storage now defaults to `inherit`, so the Phase36D worker reuses the existing governed `STORAGE_TYPE` boundary when configured (including an S3-compatible setup when configured) while retaining explicit local mode for development/acceptance. Both Local and S3-compatible backends expose a fail-closed preflight.
- Studio integration now exposes tenant-scoped media graph create/list/get, completed-graph partial revision, and final output endpoints. Public graph snapshots omit prompt metadata and physical storage keys. Revisions are rejected until the source graph is completed; non-software hardware selection is rejected at the user API unless a later operator policy explicitly enables it.
- Universal Builder integration converts its real `editable-storyboard` target into an executable Media DAG. Contract tests use the actual `_media_target()` storyboard schema rather than a duplicate fixture.
- **Real local exit-gate acceptance with FFmpeg 9.0 PASS:** V1 rendered two H.264/AAC scenes and final assembly in exactly `3` durable steps. V2 changed only `scene-b`; dependency impact was exactly `scene-b + final`, so V2 executed only `2` render steps, reused `scene-a` with unchanged checksum `434af8e834ec3877edb9db13a2ab149f99c651f1e66737869bc9792d0d303c57`, and produced a different final checksum (`c5b3a2e68fb85eeac01c75e1d28bc6a86a3651f4a730def45cd06971645ba97d` -> `873b9366e79097ab5b7d8f7b4757905c76a00704f51ae2c6f2a0829a021dd389`). Final sizes were `23698` and `23682` bytes; provenance remained attached.
- Final media-worker image built from the latest source as `sha256:07f1e5797e3fef1f4c749be7c3a8f95654cfad94b53f39645328eefd6259c590`. Image-level smoke rendered/QA-probed real H.264/AAC video (`22114` bytes), PNG (`1506` bytes), and PCM WAV (`96078` bytes); smoke JSON SHA-256 `89dc4f87ab36151bf575874f0a8f9624596274fa334b6b8427d0fb422b38caeb`. Runtime preflight reported FFmpeg `9.0`; software is the currently armed adapter while VAAPI/QSV/DRM are compiled capabilities and require an operator allowlist plus a compatible device.
- Current source verification: Phase36D DAG/worker/Alembic focused `12/12 PASS`; Studio media API `1/1 PASS`; retained Phase29H Studio regression `4/4 PASS`; root zero-dead/market-readiness `5/5 PASS`; Ruff PASS; Mypy PASS. CI now builds and runs a real FFmpeg media-worker smoke instead of validating Backend images alone.
- Production remains intentionally untouched by checkpoint 2: schema stays `0029`, no media-worker service is running, and no Production media object was created. The next protected transition is source PR/CI -> merged source -> fresh Production backup/restore -> controlled `0029 -> 0031` migration -> real inherited-S3 preflight/put-get-delete -> start media-worker -> isolated Production V1/V2 exit-gate canary -> cleanup/evidence -> only then close 36D and advance registry to 36E.


## Final source candidate — 2026-08-17T20:50Z

- The 36D execution candidate now satisfies the source/test scope without claiming Production activation. Registry maturities for `creative-asset-graph`, `media-render-transcode`, and `object-storage-media` are raised from `specified` to **`locally_executed`**; Batch 36D remains `in_progress`.
- Universal Builder's real `editable-storyboard` output is converted deterministically into render-scene nodes plus a final assembly node; the compatibility test consumes the actual `_media_target()` contract.
- Studio media graph APIs are tenant-scoped and operator-governed. Hardware selection uses `MEDIA_HARDWARE_ADAPTER_ALLOWLIST`; default remains `software`. FFmpeg 9 is compiled with VAAPI + oneVPL/QSV support, but the current non-GPU test node reports only `software` as available/armed.
- Final media-worker candidate image: `sha256:bddfbbb3de96b543eccd07c06402d1fad7c722aeefa557bcbb823b7068ee753d`. Official FFmpeg 9 source SHA/GPG verification is part of the Docker build.
- Shipped-image smoke evidence: `/opt/AIOS/.deployment-backups/phase36d-premerge/ffmpeg9-final-source-smoke.json`, SHA-256 `b4bb87cdab7844d18e5349024234de383694788e2b781dbe089aeb696c749a09`. It rendered and QA-probed final H.264/AAC MP4 (`22114` bytes), AV1/Opus WebM (`6729` bytes), PNG (`1506` bytes), and PCM WAV (`96078` bytes). Preflight: FFmpeg `9.0`; compiled accelerators `vaapi,qsv,drm`; available/armed adapters `software`.
- Final fresh regression after the last Hardware/API/WebM corrections: Backend/Studio isolated suite **36/36 PASS** on PostgreSQL 16 + Redis 7; root Phase36 governance/zero-dead/market-readiness **18/18 PASS**; Phase36 Reporting PASS; migration recovery **`0031 -> 0030 -> 0031` PASS** with fencing columns `4 -> 0 -> 4`. All disposable services were removed afterward.
- Final real worker/DB acceptance using the final FFmpeg image: V1 executed exactly `3` steps (scene A, scene B, assembly); V2 changed only scene A and executed exactly `2` steps (scene A + assembly), reusing scene B checksum `6f243cfc5afee84347e25da022772b3da773c8bcf17638f8fa7d0b5ab1bb3b21`. Final checksum changed `9fbb0f7d011ab01513c9bf162b97497c6882a0067a4c0410a5da10259ceb7eeb` -> `3b04ed02d8996c9e198944c0236344f730196bbaa7c2aa0df5e1f8cc4b19b6f0`; reused-node provenance was present. Lease recovery advanced fencing `1 -> 2`, rejected the stale worker, and completed a real recovery render.
- Production truth at this checkpoint was re-read directly: `/opt/AIOS` remains `7e418f6105a1a0426bf05130dfe56721ff520a34`, Production Alembic remains `20260817_0029`, and no Media Worker is active. Therefore no 36D capability is marked `runtime_verified` yet.
- Remaining closure sequence only: protected implementation PR/CI -> fresh Production backup + isolated restore -> deploy merged source/migrations -> start one `media-execution` worker -> storage preflight on the actually configured Production backend -> isolated Production V1/V2/fencing canary + cleanup/evidence -> post-deploy health -> mark 36D `complete` and advance to 36E.


### P36-0016 — Media Worker root entrypoint conflicted with capability dropping — 2026-08-17T21:05Z

- Production activation had already passed backup/restore, migration `0029 -> 0031`, new Backend health `10/10`, and zero active Project/Studio/Media queues. The first `media-worker` start failed before S3/FFmpeg preflight because the shared root entrypoint tried to `chown` unrelated runtime roots while the service correctly declared `cap_drop: ["ALL"]`.
- No media graph, provider call, render output or user job was created. The looping worker was stopped; Backend and database stayed healthy.
- Direct inspection proved the media volume and render temp root are already owned `1000:1000` mode `0700`, and UID 1000 can write both. A Compose-equivalent one-shot run as UID/GID `1000:1000` also completed the **real inherited S3 preflight** successfully using the configured production S3 authority without exposing credentials.
- Fix: both production Compose definitions run only `media-worker` as explicit `user: "1000:1000"`; the shared entrypoint therefore skips root-only ownership preparation while `cap_drop: ALL` and `no-new-privileges` remain intact. No Linux capability is re-added.
- Regression prevention: a Phase36D test now asserts the non-root user plus capability-drop/no-new-privileges contract in both Compose definitions. Production worker stays stopped until this fix passes protected CI and is merged.

## Phase 36D production closure — 2026-08-17T22:43Z

- Protected non-root activation fix PR #423 merged to `main` as `5989a00a9c00248771ecd076d5377a1533ba8c6a` after Backend Tests, Production Docker Build, real FFmpeg 9 media smoke, Browser boundaries, CodeQL, SBOM, Secrets, Dependency Security, Core contracts, Nginx DNS and Phase36 Reporting all passed. The fix runs only `media-worker` as `1000:1000` while retaining `cap_drop: ALL` and `no-new-privileges`; no Linux capability was re-added.
- Production schema is Alembic `20260817_0031`. Retained backup `/opt/AIOS/.deployment-backups/phase36d-production-activation/aios-20260817T213843Z.tar.gz` has SHA-256 `df2557b0d21dd064fc003c5ecfdbdf040535284be21438bcfe5104f63d40465a`; archive inspection found exactly one SQL entry. Isolated PostgreSQL 16 restore smoke returned Alembic `0031` with media graphs/steps, active ProjectExecutions and active Studio jobs all `0`.
- Production Media Worker runs healthy as UID/GID `1000:1000`; worker health reports FFmpeg `9.0`, armed hardware path `software`, and worker errors `0`. The inherited Production S3-compatible storage authority passed preflight without exposing credentials.
- **Real Production exit gate PASS:** evidence `/opt/AIOS/.deployment-backups/phase36d-production-activation/phase36d-production-exit-canary-20260817T223917Z.json`, SHA-256 `306c97de5cda178cea0cb46a5e948867bdc8a80a8d48c8a85022fa56ddc13b0c`. V1 executed `3` steps (scene A, scene B, final assembly). V2 changed only `scene-a`, executed `2` steps (`scene-a + final`), reused `scene-b` with identical checksum and `reused-render` provenance, changed the final checksum, stored outputs on S3, materialized two Studio revisions and advanced `StudioAsset.current_revision` to `3`. All `5` canary S3 keys were deleted; DB cleanup returned organization/graphs/steps `0`.
- **Production recovery/fencing PASS:** evidence `/opt/AIOS/.deployment-backups/phase36d-production-activation/phase36d-production-fencing-result-20260817T224129Z.json`, SHA-256 `20ee53ae986a687eb3dca1fe39eedfdb6f3edc241bf0c056bb84e246e286dae3`. A synthetic expired lease was reclaimed by the live worker, attempts advanced to `2`, fencing generation advanced from `1` to `2`, `reclaimed=true` was retained in audit evidence, the recovery render completed on S3, and the recovery S3 object plus all synthetic DB rows were removed.
- Final Production snapshot after both canaries: Backend, PostgreSQL, Redis, Nginx, Studio Worker, both Project Workers and Media Worker healthy; Backend `/ready` `10/10` HTTP 200; Project/Studio/Media active queues `0`; synthetic Phase36D canary organizations `0`; critical/traceback/panic/fatal log hits across Backend, Media Worker and both Project Workers `0`.
- Evidence-backed maturity transition: `creative-asset-graph`, `media-render-transcode`, and `object-storage-media` are `runtime_verified`. Batch **36D is complete**; Batch **36E becomes in_progress** and is the authoritative `current_batch`. This closure starts no 36E image/design provider work by itself.
