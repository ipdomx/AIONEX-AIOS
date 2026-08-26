# Phase 36G post-closeout activation — Open Song artifact bridge preflight

Date: 2026-08-26

Status: **SOURCE VALIDATED — protected merge, final image supply-chain evidence, and paid RunPod runtime acceptance remain pending**

This preflight does not reopen Phase 36 and does not claim that `song-production` is runtime verified. It records the source-level safety work required before the already-documented `ace-step-open-song-runtime-acceptance` external gate can be exercised.

## Scope

The Open Song RunPod handler no longer depends on the stale AWS/S3 artifact credentials previously present in the Production environment. The candidate source now uses a private AIONEX artifact bridge:

- the Backend creates five opaque 192-bit artifact IDs and short-lived, action-scoped HMAC upload grants;
- upload grants are sent only in `Authorization` headers and are never embedded in URLs;
- the RunPod handler may upload only to the exact `https://api.vip-e.net/api/v1/audio-song-artifacts/<48-hex-id>` contract;
- the handler returns only the opaque artifact ID plus SHA-256, size, media type, duration, sample rate, and channel evidence;
- the durable song execution does not persist upload/download/delete tokens or signed artifact URLs;
- after the worker verifies and durably stores the full song plus four stems, it creates fresh delete grants and removes ingress copies; TTL purge remains the fallback for abandoned ingress objects;
- the public Nginx body-size exception is isolated to the exact artifact bridge path and does not raise the limit for the rest of the API;
- the Backend gets a dedicated ingress volume instead of write access to the Studio or Media store;
- `boto3` and all `AIONEX_ARTIFACT_S3_*` runtime requirements were removed from the GPU handler.

Source commit containing the bridge implementation before this receipt: `b3590ca`.

## Validation evidence

- Open Song backend/runtime/provider/worker/bridge suite on disposable PostgreSQL migrated through `20260825_0043`: **40 passed, 1 skipped**.
- GPU handler contract and direct artifact-publisher suite: **12 passed**.
- Ruff on the changed Python/handler tests: **PASS**.
- Mypy on the four changed Backend source modules: **PASS — no issues found**.
- `nginx -t` against the changed Production config: **PASS**.
- `docker compose --env-file .env.production -f docker-compose.production.yml config --quiet`: **PASS**.
- `git diff --check`: **PASS**.
- staged secret-pattern review found no RunPod, Cloudflare, AWS, or private-key material.
- disposable PostgreSQL container and test network were removed after validation.

## Explicitly not claimed by this receipt

- no new RunPod Open Song Serverless Endpoint has been created yet;
- no paid Open Song generation was submitted by this preflight;
- no full-song/four-stem Production artifact bundle has been accepted yet;
- no Studio master/export acceptance is claimed here;
- `song-production` remains `source_built` until the real bounded runtime chain succeeds;
- the pre-bridge SBOM SHA-256 `3c21907f39b8ad3d07680c28e73eb27cc3c3aebcc4ec97fde63b91deaabe8c25` is historical candidate evidence only and must not be used as the final image SBOM after this source change;
- `music-rights-and-ai-generated-disclosure` remains an explicit policy gate.

## Next gate

Protected CI must merge the bridge first. Then the Backend/Nginx bridge can be deployed without Cloudflare mutation, the final GPU image can be rebuilt from the merged source, a new SBOM and vulnerability report can be generated, the immutable image can be pushed and bound to a scale-to-zero RunPod Endpoint, and exactly one bounded Open Song acceptance can be executed with no automatic retry or cross-provider fallback.

## Public ingress method compatibility follow-up

Production preflight after PR #518 deployment proved the signed artifact bridge itself reaches `201` through the internal Nginx path, while Cloudflare rejects `PUT` before origin with `403`. Read-only method reachability showed `POST`, `GET`, and `DELETE` reach origin without any Cloudflare or tunnel mutation. The upload transport is therefore constrained to HTTPS `POST`; the HMAC grant scope remains the existing bounded `put` action. Runtime Open Song acceptance remains pending until the new transport passes protected CI, production deployment, and a full RunPod song/stem execution.
