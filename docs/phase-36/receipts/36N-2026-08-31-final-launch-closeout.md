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

## Post-deploy continuation — protected merge and live publication

Protected PR #535 merged to `main` as `519958354d8a95111b9958393fe23ce653de6fff` after every required check passed. The final `Production Docker Build` completed successfully in `20m59s`, including core images, FFmpeg 9 media worker, live-disabled speech/transcript/dubbing/music/video workers, Sharp derivative worker, Security Lab image/toolchain, legacy `DATABASE_URL` data-preservation, legacy `.env` upgrade, and backup/restore round-trip.

The AIOS server working tree was then updated to the exact merged main SHA over an authenticated HTTPS fetch without changing the persistent Git remote configuration.

### Owner selective deployment

Only the Owner frontend service was rebuilt/recreated. Backend, Nginx, PostgreSQL, Redis and all workers were intentionally left running.

The previously running Owner image had already been pruned from the local image store, so a direct Docker tag/commit could not provide a safe rollback anchor. Before mutation, the exact pre-change source `8e010082dcf88e761dc6e74f990a6b514dc7e18a` was checked out in a temporary worktree and rebuilt with the same Dockerfile and `NEXT_PUBLIC_USER_PORTAL_URL=https://ai.vip-e.net`. That rollback image is retained as `aionex-aios-frontend:rollback-final-launch-20260831T102031Z`, image ID `sha256:b4844784b62e137b87599e8d64296340883cbb0836e4e1548cb0c9df251515fd`.

The merged Owner image built successfully as `sha256:240a2cb8215d094c2a85074ad29110137a50262b3f63250390c5b3d2cf6a07b1` and is also retained as `aionex-aios-frontend:release-519958354d8a`. `web-dashboard-frontend-1` alone was recreated; it reached `healthy` with restart count `0`. Direct private-origin HTTP checks returned `200` for `/`, `/infrastructure/containers`, `/infrastructure/databases` and `/infrastructure/servers`; API `/ready` remained `200`.

### `ai.vip-e.net` shared-hosting publication

The merged VIP source was re-verified immediately before publication: integrity `96` files / `6` complete locales / no simulated-data markers, TypeScript PASS, ESLint PASS, static build `127` pages, static smoke `94` URLs.

Before rsync, the live shared-hosting document root was archived to `/home2/ipdom3m7/.aionex-deploy-backups/20260831T102031Z-final-launch-closeout/ai-vip-before-final-launch-closeout.tar.gz` (5,762,222 bytes; SHA-256 `85603fcee39274257b21cfafc9973a0edae3d250f72486d325ce938b118629ea`, mode `0600`). Publication used the established `aionex-cpanel-ai-vip` SSH route, `--delete`, and explicit preservation of `.well-known/acme-challenge/` plus hosting-owned `cgi-bin/` if present. `.well-known/assetlinks.json` remains present.

Post-publication checksum-only rsync parity returned exactly `0` difference lines. Live external HTTP acceptance returned `200` for all six locale roots (`ar`, `de`, `en`, `es`, `fr`, `tr`) and each locale's `login`, `projects`, `studio` and `academy` routes. Public `/`, `robots.txt`, `sitemap.xml` and `.well-known/assetlinks.json` all return `200`. Each of the six live locale-root HTML responses matched the local deployed `index.html` SHA-256 exactly.

External boundaries remain correct: `https://api.vip-e.net/ready` returns `200`; `https://gabarot.vip-e.net/` returns the expected Cloudflare Access `302`. No Cloudflare DNS or Tunnel mutation was made.

### Final production and cleanup state

All `29` running `web-dashboard` Production containers were checked after publication: `bad=0`, every health-labeled container is `healthy`, and all restart counts are `0`; `cloudflared` is running without a Docker healthcheck as before. Disposable audit PostgreSQL/Redis, Trivy containers and the audit network were removed. No audit/Trivy containers remain. The pinned hardened Hunyuan candidate and Owner rollback image are intentionally retained. Root filesystem usage after cleanup is approximately `39%`, with about `513 GB` free.

No paid GPU/provider generation was used, Production databases were never used for the test suites, and `HUNYUAN_RUNTIME_SECURITY_APPROVED` remains `False` pending a separate GPU functional/PBR acceptance. TripoSR remains the approved 3D fallback. External legal/store/realtime/provider gates remain explicit and are not represented as completed by this deployment.

## Integrated runtime, 3D DR and SMTP closure — 2026-09-03

The remaining internally actionable launch-closeout items were completed after the initial publication receipt. No Cloudflare DNS/Tunnel mutation, paid GPU generation, or production test-data injection was used.

### Protected merges and runtime image

Protected PR #539 (`backup: protect local 3d assets in disaster recovery`) completed all `16/16` required checks and merged to `main` as `9a106d368305d1b673c18b3bb7e17e6c8742e493`. Protected PR #540 (`fix: support implicit TLS for SMTP delivery`) completed all `12/12` required checks and merged to `main` as `b37a68e50272314ff840db08217792ae1ecbbfee`.

The final Backend image built from the merged source is `sha256:4c25cb9e6e85123e437418113ebe7815525cbbda6d24f7f05e0143d8a9e9f274`. The immediate pre-SMTP-fix Backend rollback image is retained as `aionex-aios-backend:rollback-pre-smtp-ssl-20260902T195542Z`, image ID `sha256:0b1fa532f5e2d4bdc66169345f166744b155d0087dcc09253b28c22387a8be92`.

All running services whose logical image is `aionex-aios-backend:local` were selectively recreated only after the relevant active-work queues were verified empty. Final Backend-image drift is `0`; every recreated service reached `healthy`, restart count `0`. Project worker scale remains the documented Production baseline of `2/2`, both healthy with restart count `0`.

### Production 3D disaster recovery proof

Production 3D storage remains private local durable storage with `BACKUP_THREE_D_ASSETS_ENABLED=true`. Backend and the 3D worker retain read/write access; Project workers retain read-only access; the Backup worker consumes the 3D volume read-only.

A real Production platform backup was created through the governed durable backup worker as `417a4e61-e056-41df-a30e-b4a368177edd`. It completed with PostgreSQL archive location `/var/lib/aionex/backups/backup-b3645b14b03122f1e059a6fd-ff4ff6cb24d0d239afc384171f48dca0.dump`, size `17,673,783` bytes, SHA-256 `e1e198fdda556d0cac8be000d0fcf1a39bb993f7cf9498fd61f8912038ab2690`.

The same platform backup produced a required immutable 3D companion snapshot with SHA-256 `4f972bd6abdcc1f3b049979da5c852cc519e5dd695856d7a82d338a4b683da22`, archive size `10,240` bytes. Its file count and payload bytes were `0` because no paid 3D generation was invoked merely to populate the volume for acceptance.

A real Production restore validation was then executed against the exact same backup as Disaster Recovery run `7014ccd5-904a-4720-b985-4990a0c25d89`. It completed with `validated=true`, `three_d_snapshot_required=true`, and `three_d_snapshot_validated=true`. The database archive checksum and 3D companion checksum matched their backup evidence. No scratch restore database remained after the run.

The Owner recovery gate reports `passed`; Security operational assurance reports recent backup and recent restore evidence as valid; Operations `Backup & Restore` reports `healthy` and readiness `100`.

### SMTP implicit TLS closure

Production SMTP is configured for implicit TLS (`SMTP_SSL=true`) on port `465`. The Password Reset path already honored this policy, but the governed notification sender and Owner test-email helper still instantiated plain `smtplib.SMTP`. PR #540 corrected both call sites to use `smtplib.SMTP_SSL` when `SMTP_SSL=true`, while retaining STARTTLS only for non-SSL SMTP policy.

The fix passed focused fake-client tests without network delivery, Ruff, Mypy (`247` Backend source files), `verify_backend.sh`, Core (`849/849`), and the full isolated Backend suite (`1097 passed, 1 skipped, 0 failed`). After protected merge and selective deployment, a no-send live acceptance from the Production Communication worker completed SMTP SSL authentication plus `NOOP` with code `250`.

### Final integrated acceptance

The final source SHA on the server matches GitHub `main`: `b37a68e50272314ff840db08217792ae1ecbbfee`.

At final acceptance:

- all running Production containers were healthy/running with restart count `0`; no bad container was found;
- Backend logical-image drift was `0`;
- Project workers were `2/2` healthy;
- Project, 3D, design, video, speech, transcript, dubbing, music, song, backup, restore and notification active-work counts were all `0`;
- Operations readiness was `100`, with Database, Redis, Backend, Runtime Components, Operations and Backup all `healthy` / readiness `100`, `0` unavailable runtime components and `0` active alerts;
- TripoSR was configured, 3D storage was `local`, and 3D backup protection was enabled;
- `HUNYUAN_RUNTIME_SECURITY_APPROVED` remained `False` and Hunyuan runtime remained unconfigured/fail-closed pending its separate paid-GPU PBR functional acceptance;
- Project AI, image, video, speech, transcript, dubbing, music and song live-execution flags remained `False`;
- model inventory evidence contained `6` validated models across `4` providers and was refreshed automatically by the four-hour Operations observer;
- SMTP SSL authentication plus no-send `NOOP` returned `250`;
- `https://api.vip-e.net/ready` returned `200`;
- `https://ai.vip-e.net/` and all six locale roots (`ar`, `de`, `en`, `es`, `fr`, `tr`) returned `200`;
- `https://gabarot.vip-e.net/` returned the expected Cloudflare Access `302`;
- UFW was active with inbound SSH rate-limited; Fail2ban was active; failed systemd unit count was `0`;
- no disposable audit/test containers remained;
- root filesystem usage was approximately `40%`, with approximately `507 GB` free.

A final runtime-source marker sweep found no mock/fake/demo data or placeholder implementation in Production runtime paths. Remaining `NotImplementedError` references are either exception-handling fallbacks or intentional abstract base-class contracts covered by the project's zero-dead audit.

Externally controlled gates are still represented truthfully rather than fabricated as complete: unconfigured payment providers remain unconfigured, store-signing/legal/realtime/provider-funding gates remain explicit where applicable, and Hunyuan remains fail-closed until separate GPU functional acceptance. All internally actionable defects identified by this comprehensive closeout were repaired, protected by regression tests, merged through required CI, deployed selectively, and verified live.
