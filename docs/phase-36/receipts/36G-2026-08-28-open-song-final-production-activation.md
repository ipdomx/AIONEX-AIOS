# Phase 36G — Open Song final Production activation

- Receipt ID: `36G-2026-08-28-open-song-final-production-activation`
- Date/time UTC: 2026-08-28
- Scope: post-merge activation and final live-state reconciliation for the already-passed Open Song runtime acceptance. No new GPU acceptance job was submitted in this activation.

## Merged source and protected checks

PR #525 merged normally into `main` after all required checks passed. Merge commit:

`ccd6b2d5e06ac9b0d0768ea74a12999589bfb5fc`

Protected checks recorded PASS for Backend Tests, Production Docker Build, Backend SBOM/vulnerability gate, CodeQL Python and JavaScript/TypeScript, Core Owner/Release/Web Contracts, Dependency Security, Frontend Build, Owner/VIP browser boundaries, Phase 36 Reporting Invariant, and repository secret/hygiene audit.

The Production detached checkout `/opt/AIOS` was advanced from `beb9a2cf1f14eaa6fa47ae378eb081ebe3a2d308` to the merged `main` commit above. No tracked local Production change was overwritten; the existing `.worktrees/` directory remained untouched.

## Backend-only Production activation

Before activation the live Backend still reported `song-production=source_built` with the already-satisfied `ace-step-open-song-runtime-acceptance` gate because its container image predated PR #525.

Only the Backend image/container was rebuilt and recreated from merged source. No Portal, Owner UI, Nginx, Cloudflare Tunnel/DNS, database migration file, or audio provider submission was changed.

- Previous Backend image ID: `sha256:7def5397c5967d39c7eb2ea88a724b30eb05db355039449c70a50e359a0a5dd0`
- Rollback tag retained: `aionex-aios-backend:rollback-phase36g-final-20260828T050232Z`
- Activated Backend image ID: `sha256:b3301bc448b41a50841ff876fbde84fc59a49b86fcc6f980f6b7b94845abe1c0`
- Backend post-activation health: `healthy`
- Backend restart count: `0`
- Alembic after activation: `20260825_0043 (head)`
- Backend critical/traceback/fatal/unhandled-exception matches in the activation window: `0`

The live Backend capability snapshot now reports:

- `current_batch=COMPLETE`
- `song-production=runtime_verified`
- remaining Open Song external gate: `music-rights-and-ai-generated-disclosure`
- `ace-step-open-song-runtime-acceptance` is no longer an external gate because the bounded runtime acceptance passed.

## Open Song runtime state preserved

The accepted immutable Open Song runtime remains:

- image digest: `sha256:6b6ce10bda3adc378fff230b307ac1ce9f86aaf21d82cd6e1f9c9b9f2a19ea34`
- handler source SHA-256: `15f8b34e8f45ce3f156cd2d0e00df532acd3803e5bdff4370ab670e634652a37`
- SBOM evidence mode: derived package-equivalent, explicitly not a fresh full scan
- derived SBOM SHA-256: `ea9d47313f92ed7af3eb643182b372c18d1d2eea8291af8f63f15e9c30395f11`

The production audio-song worker remained `healthy`, restart count `0`, and `AUDIO_SONG_LIVE_ENABLED=false` throughout this activation.

The RunPod endpoint retained only the successful governed acceptance history: `completed=1`, `failed=0`, `inProgress=0`, `inQueue=0`, `retried=0`. A later standby state of `throttled=1` carried no queued/running work and is not an execution failure.

Acceptance v8 remains the authoritative runtime proof: exactly one provider submission, `attempts=1`, `retried=0`, Full Song plus four stems plus mix/master/export/waveform completed, Studio revision `2`, final audio QA PASS, actual cost `$0.02584`, and synthetic cleanup residue returned to zero.

## Evidence and rollback

- Final Production activation evidence directory: `/opt/AIOS/.deployment-backups/phase36g-open-song-final-activation/20260828T050232Z/`
- Final live-verification SHA-256: `f5a2f79ca490c514061bea8ba4a29217ef514a52eaa82ec6c0cb33b82fc185ed`
- Acceptance v8 evidence SHA-256: `ad01ab9ed9c694b5ac9f5dfa5b5caec968b60b6a16300d8c64ae1cd985f632c5`

Rollback can restore the retained pre-activation Backend image without changing the accepted RunPod image/binding.

## Final boundary

The internal Open Song runtime acceptance and Production registry activation are complete. Music-rights/AI-generated disclosure remains an explicit external evidence gate and is not represented as unfinished internal implementation. The secondary RunPod account remains intentionally deferred by owner direction and was not activated, copied, or used in this closeout.
