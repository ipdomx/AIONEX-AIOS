# Phase 36D — Universal Creative Asset Graph & Media Orchestrator

Date: 2026-08-17
Status: **IN PROGRESS — foundation checkpoint 1**

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
- Media storage now defaults to `inherit`, so the Phase36D worker reuses the existing governed `STORAGE_TYPE` boundary when configured (including the current S3 setup) while retaining explicit local mode for development/acceptance. Both Local and S3-compatible backends expose a fail-closed preflight.
- Studio integration now exposes tenant-scoped media graph create/list/get, completed-graph partial revision, and final output endpoints. Public graph snapshots omit prompt metadata and physical storage keys. Revisions are rejected until the source graph is completed; non-software hardware selection is rejected at the user API unless a later operator policy explicitly enables it.
- Universal Builder integration converts its real `editable-storyboard` target into an executable Media DAG. Contract tests use the actual `_media_target()` storyboard schema rather than a duplicate fixture.
- **Real local exit-gate acceptance with FFmpeg 9.0 PASS:** V1 rendered two H.264/AAC scenes and final assembly in exactly `3` durable steps. V2 changed only `scene-b`; dependency impact was exactly `scene-b + final`, so V2 executed only `2` render steps, reused `scene-a` with unchanged checksum `434af8e834ec3877edb9db13a2ab149f99c651f1e66737869bc9792d0d303c57`, and produced a different final checksum (`c5b3a2e68fb85eeac01c75e1d28bc6a86a3651f4a730def45cd06971645ba97d` -> `873b9366e79097ab5b7d8f7b4757905c76a00704f51ae2c6f2a0829a021dd389`). Final sizes were `23698` and `23682` bytes; provenance remained attached.
- Final media-worker image built from the latest source as `sha256:07f1e5797e3fef1f4c749be7c3a8f95654cfad94b53f39645328eefd6259c590`. Image-level smoke rendered/QA-probed real H.264/AAC video (`22114` bytes), PNG (`1506` bytes), and PCM WAV (`96078` bytes); smoke JSON SHA-256 `89dc4f87ab36151bf575874f0a8f9624596274fa334b6b8427d0fb422b38caeb`. Runtime preflight reported FFmpeg `9.0` and adapters `software,vaapi,qsv,drm`.
- Current source verification: Phase36D DAG/worker/Alembic focused `12/12 PASS`; Studio media API `1/1 PASS`; retained Phase29H Studio regression `4/4 PASS`; root zero-dead/market-readiness `5/5 PASS`; Ruff PASS; Mypy PASS. CI now builds and runs a real FFmpeg media-worker smoke instead of validating Backend images alone.
- Production remains intentionally untouched by checkpoint 2: schema stays `0029`, no media-worker service is running, and no Production media object was created. The next protected transition is source PR/CI -> merged source -> fresh Production backup/restore -> controlled `0029 -> 0031` migration -> real inherited-S3 preflight/put-get-delete -> start media-worker -> isolated Production V1/V2 exit-gate canary -> cleanup/evidence -> only then close 36D and advance registry to 36E.
