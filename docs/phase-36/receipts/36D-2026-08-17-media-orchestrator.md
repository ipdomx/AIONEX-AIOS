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
