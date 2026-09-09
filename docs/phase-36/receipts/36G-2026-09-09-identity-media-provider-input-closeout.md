# Phase 36G — Identity Media Provider Input Closeout — 2026-09-09

## Scope

This receipt closes the production correction and acceptance of governed Identity Media provider inputs. The accepted transport is a short-lived HMAC-authenticated HTTPS pull bridge from private AIONEX object storage. It replaces Replicate Files URLs that require account authorization and therefore cannot be fetched by an isolated third-party model runtime.

Only fictional/generated fixtures were used. No real-person or public-figure likeness was submitted, and the existing rights, disclosure, Owner-grant and licensed-catalog gates remain unchanged.

## Protected source changes

Three protected pull requests form this closeout:

- PR `#598`, **Fix signed provider inputs for Identity Media**, merge commit `dbedface9351f4029e8f40d0c9ec5c2cee702fe2`.
  - Added short-lived signed input grants, signature and expiry verification, execution/input binding, private-object preflight and streaming delivery.
  - Replaced provider-facing bearer-protected Replicate Files URLs with scoped HTTPS pull URLs for every Identity Media input.
  - Preserved provider job IDs and credentials as private runtime details.
  - Included transport/lifecycle tests and the frontend/image-derivative security upgrades.
- PR `#600`, **Allow signed Identity Media provider inputs through Nginx**, merge commit `593ca8d867c34e72c38638bbc33853568dac7a9d`.
  - Added one exact public route for `/api/v1/studio/identity-media/provider-input/<signed-token>/<filename>`.
  - Kept all other Studio routes private.
  - Enforced GET/HEAD only, stripped inbound Authorization and Cookie headers, disabled access logging and proxy buffering, and applied rate, connection and timeout bounds.
- PR `#601`, **Prevent signed provider URLs in Nginx error logs**, merge commit `5c3b8ac59d08e3dcd7717dca86ff2eaec763d57a`.
  - Added location-scoped `error_log /dev/null crit;` so rejected methods and upstream errors cannot write a signed URI.
  - Added a regression assertion for the no-error-log contract.

All checks reported by each PR completed successfully before its production change was accepted. For PR `#601`, this included Backend Tests, Production Docker Build, CodeQL for Python and JavaScript/TypeScript, SBOM/vulnerability, dependency security, frontend build, Owner/VIP browser boundaries, Docker DNS re-resolution, repository hygiene and Phase 36 reporting checks. No branch-protection bypass was used.

## Pre-deploy protection and rollback

The protected pre-deploy backup completed before the Identity Media runtime rollout:

- Backup ID: `2f3fbc2f-c637-4c9b-ad27-f42f3e4b4f6a`.
- Kind: `pre-identity-provider-input-fix-20260909`.
- Local status: `completed`.
- Off-site status: `completed`.
- Completed at: `2026-09-09 14:21:15Z`.
- Size: `20,831,828` bytes.
- SHA-256: `fe18d53cc4fb56e4f894e5435db32ab169377b2209bc214ea01a6d2548a614c4`.

Exact rollback references were retained:

- Backend / Identity worker: `aionex-aios-backend:rollback-pr598-backend-20260909T142115Z` -> `sha256:c35fb28746d1c583e348da29db21eeede47919fb653e00e35e644869a5ae3a6b`.
- Frontend: `web-dashboard-frontend:rollback-pr598-20260909T142115Z` -> `sha256:fc29cd23fd0d7eb34ff761e626fba476e98756ca3a5b19ccf0e98a08ae911563`.
- Image derivative worker: `aionex-aios-image-derivative-worker:rollback-pr598-20260909T142115Z` -> `sha256:e3768c347932d9e6606ea5e1a41c56ff1faf4ebca3fb8c32401dcf58ea0c87ba`.
- Design worker flattened rootfs recovery image: `aionex-aios-backend:rollback-pr598-design-20260909T142115Z` -> `sha256:d5d778b5e9c9993d066bdb855eb77445cb1b2d782a16f3a47e07a08a7a07c774`.
- Nginx runtime image reference: `aionex-aios-nginx:rollback-pr600-20260909T144600Z` -> `sha256:ad1cd14808d782f285c0c21b0d2ecb2336eb2344167a8ce0cfac5316b0cd9ab1`. Nginx configuration is source bind-mounted, so its exact configuration rollback authority is the protected Git history above.

## Production deployment

The merged Identity Media rollout uses:

- Backend, Identity worker and Design worker image: `sha256:ef090abd86748bb8e37bf252b95471b340d70a845e41f4652c5ff647b3979ca5`.
- Frontend image: `sha256:6a82faf354696dc7cbd0443de587e8165c69817ec86e630af5203622f54a73df`.
- Image derivative worker image: `sha256:d1c39d3c4f264ed46a4274fbcc875f2f5e9e335ebd9b304e9ed52f99d2dbfcc0`.

After PR `#601`, only Nginx was force-recreated. Its final health is `healthy`, restart count is `0`, and the loaded configuration contains the route-scoped access- and error-log suppression.

Public ingress acceptance returned:

- Valid-shaped, invalid-signature GET: HTTP `404`, `application/json`, proving the request reached backend signature verification.
- Unlisted Studio GET: HTTP `404`, `text/html`, proving the private boundary remains in force.
- Valid-shaped POST: HTTP `403`, `text/html`, proving the method restriction remains in force.
- Unique GET and POST marker counts in Nginx logs: `0|0`.
- Post-canary provider-input URI counts in Nginx and Backend container logs: `0|0`.

No signed token or provider job identifier is recorded in this receipt.

## Ambiguous v7 containment and manual clearance

The first post-PR-`#598` voice attempt exposed the missing Nginx allowlist and was contained safely:

- Execution: `7f6af527-7d9e-43a7-88f7-0aaa7090a4a7`.
- Created: `2026-09-09T14:39:45.100721Z`.
- Terminal state: `needs_review`.
- Error code: `provider_submission_ambiguous`.
- Submission attempts: `1`.
- Polls: `0`.
- Provider job ID: absent.

The row was not retried or altered. Immediately before the replacement canary, the authenticated Replicate predictions list returned HTTP `200`; one authoritative page covered the interval beginning `2026-09-09T14:39:44Z` and contained `0` predictions. The new voice execution has a durable `identity_media.launch_canary.queued` audit event recording the prior execution, absent provider job, provider-history check, zero matching predictions and the independent-new-execution basis.

## Accepted production canaries

### Voice Clone v8

- Execution: `d90288bc-05ff-4aff-92d1-83941c841377`.
- Idempotency key: `identity-launch-canary-20260909-voice-v8-signed-pull`.
- Identity basis: `fictional_inspired`.
- Final status / provider state: `completed / succeeded`.
- Attempts / polls: `1 / 3`.
- Provider input transport / names: `signed_https_pull / ["audio"]`.
- Primary and secondary provider jobs were durably bound; their identifiers remain private.
- Final stage: `cloned_speech`.
- Voice identifier returned to client: `false`.
- Output: `audio/mpeg`, `56,436` bytes.
- Output SHA-256: `617873cd6a085f277f836cf3700daf352f572f8e10eb59f503672d9e48dcfe83`.
- Completed: `2026-09-09T15:50:31.092857Z`.

### Lip Sync v6

- Execution: `5fbac826-c9df-4904-8b81-0e93ee7d9edf`.
- Idempotency key: `identity-launch-canary-20260909-lipsync-v6-signed-pull`.
- Identity basis: `fictional_inspired`.
- Final status / provider state: `completed / succeeded`.
- Attempts / polls: `1 / 18`.
- Provider input transport / names: `signed_https_pull / ["video", "audio"]`.
- Output: validated `video/mp4`, `2,922,455` bytes.
- Output SHA-256: `bf27746a84048b1f77ab6b2906ccbac77aedda2bf85ff62a161afcaf857a34e8`.
- Completed: `2026-09-09T15:52:01.119546Z`.

Both executions used a `$1.00` user-authorized ceiling. Provider-reported actual dollar cost was not asserted; the durable basis remains `user_authorized_ceiling_provider_price_unverified`.

## Bounded cleanup and final health

Only the two known test-only Replicate Files were deleted:

- `Mzg4OWI2YTItNTBmOS00MTVjLTk4M2MtNmMxNjEwNzMxMGRm.wav`: DELETE `204`, verification GET `404`.
- `Mzk4MWYxYzUtNmRhYS00NjE1LTg5ZjctOTgyNDMzMTg0OTE1.wav`: DELETE `204`, verification GET `404`.

The temporary `test-sharp0354-20260909` derivative image and the temporary canary controller were removed. Durable database rows, audit evidence, private canary inputs and accepted outputs were retained.

Final production snapshot:

- Backend `/ready`: HTTP `200`, `application/json`.
- Compose project: `40` containers total.
- Running services: `36`.
- Completed one-shot containers: `4`, all exit code `0`.
- Unhealthy, unexpected-exit or restart exceptions: `0`.
- Aggregate restart count: `0`.
- Active Identity Media executions: `0`.

## Boundaries retained

This closeout made no Cloudflare or DNS change, did not touch the second RunPod account, AWS/Bedrock/XR, mobile-store publication, deferred payment-gateway work or unrelated provider assets. Licensed public figures remain fail-closed without an actual licensed-catalog authority. The accepted evidence covers only the fictional/generated Voice Clone and Lip Sync paths described above.
