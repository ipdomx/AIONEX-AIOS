# Phase 36N — Final launch closeout continuation — 2026-08-31

## Purpose

This receipt records the final source/security/runtime closeout performed after the comprehensive pre-launch audit. It does not turn external-provider, legal, store-signing, realtime-network, or paid GPU acceptance gates into fake completion.

## Hunyuan3D hardened candidate

A reproducible Hunyuan3D source candidate was built from `infra/runpod/hunyuan3d/Dockerfile` as `aionex-hunyuan3d:pinned-release-20260831`, exact local image ID `sha256:95c38e05f99a134be3c61bbc746a070a0376a17fdce0f36143df9bc5b69dedd7` (42,074,807,200 bytes).

The image removes inherited server/development baggage that is not part of the RunPod inference path, including SSH, Nginx, Python 3.11/Jupyter runtime residue, npm runtime, development headers/tooling, and the old Gradio UI runtime. Runtime dependencies are pinned and `pip check` is a build gate. `ninja==1.13.0` replaced the incompatible inherited `1.11.1.1`; `pip check`, DeepSpeed import and Hunyuan shape/paint import contracts passed. Sharp is `0.35.4` with libvips `8.18.6`. Blender executes `bpy 3.0.1` through the intended isolated Blender CLI path.

DINO assets are now revision-pinned to the exact revision found in the previously accepted runtime: `facebook/dinov2-giant@611a9d42f2335e0f921f1e313ad3c1b7178d206d`. Runtime sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and `HF_DATASETS_OFFLINE=1`; the RunPod request contract exposes no model, repository or checkpoint selector.

Trivy `0.73.0` on the exact pinned image reported `2 Critical / 6 High / 633 Medium / 100 Low`. The eight High/Critical findings are exactly the eight package/version-scoped statements in `infra/runpod/hunyuan3d/openvex.json` (SHA-256 `459caabf9a914a7b2d458e38034d0c8b37fb2e1e0046140d5122ac89f9c875ef`). There are no wildcard suppressions. Raw report SHA-256: `10f34f45a0c1d19cac11ad6f2ac5cfa7b7c0990cacf553c33a6fbfd1fe8d3864`. Trivy with the exact OpenVEX returned exit `0` and `0 High / 0 Critical`; VEX-applied report SHA-256: `25a2cfb4182a87c781bac6d294ddc45ebf76c89ee31c81093a7f013943c114a2`.

The source-controlled production gate **remains closed**: `HUNYUAN_RUNTIME_SECURITY_APPROVED=False`. Security acceptance of the source image does not substitute for the required paid-GPU functional/PBR acceptance. The existing production Hunyuan v11 digest remains quarantined and TripoSR remains the approved 3D fallback.

## Mock/runtime source-of-truth cleanup

The obsolete in-memory `identity_store.py` and `runtime_store.py` were removed after repository-wide import review proved that no production endpoint or service imports them. The obsolete `test_runtime_batch2.py`, which only validated the removed mock store, was removed with them. Current tests explicitly forbid those stores from reappearing in SQL-backed endpoints.

A disposable PostgreSQL environment was migrated from zero through Alembic `20260825_0043`. Focused identity/runtime/Owner SQL source-of-truth regression completed `27 passed`; Production PostgreSQL and Redis were not used. `verify_backend.sh` passed in a disposable writable copy with the monorepo `src` package mounted read-only. Ruff passed and Mypy reported no issues in 246 backend source files.

## Owner dashboard API repair

The Owner operations client previously called legacy top-level paths for containers, databases and servers. These were corrected to:

- `/infrastructure/containers`
- `/infrastructure/databases`
- `/infrastructure/servers`

`npm run type-check` now includes a source-controlled API-contract regression gate that requires the corrected paths and rejects the legacy paths. A broader contract sweep compared 177 literal frontend API references with the live FastAPI application contract and found zero missing literal paths.

Owner verification: API-contract PASS; TypeScript PASS; ESLint PASS; Arabic coverage PASS (`991` translatable UI strings, `5` approved technical tokens); Next.js production build PASS with `90` static pages.

## VIP portal deployment route and validation

The authoritative routine deployment route for `ai.vip-e.net` is the existing shared-hosting SSH path, **not** a Cloudflare DNS/Tunnel mutation:

`aionex-cpanel-ai-vip` -> `/home2/ipdom3m7/ai.vip-e.net/`

The alternate AIOS `nginx:8082` listener remains a staging/alternate origin. Routine publication is static verification/build -> remote backup -> rsync -> checksum parity -> live HTTP acceptance. `cgi-bin/` and `.well-known/acme-challenge/` are hosting-owned and must be preserved.

Current VIP source verification passed: 96 files, six complete locales, no simulated-data markers, TypeScript PASS, ESLint PASS, 127-page static build PASS, and 94-URL static smoke PASS. A read-only rsync dry-run against the live document root showed 495 change lines, confirming the live portal is behind the current build and requires publication after protected merge. The shared-hosting filesystem had approximately 724 GB free at preflight.

## Pre-merge production invariants

Before this change is merged and deployed: Backend, Owner frontend, Nginx, PostgreSQL and Redis production containers are healthy; API `/ready` returns 200; `ai.vip-e.net` representative locale pages return 200; `gabarot.vip-e.net` returns the expected Cloudflare Access 302. No paid provider/GPU generation was invoked, Production databases were not used for test execution, and no Cloudflare DNS/Tunnel mutation was performed.

## Deployment boundary

This receipt certifies the source candidate and pre-deploy gates. Protected CI, merge identity, selective Owner publication, shared-hosting backup/rsync checksum parity, live HTTP acceptance, and final cleanup are recorded in the post-deploy continuation once completed.
