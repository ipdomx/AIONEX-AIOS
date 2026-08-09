# Phase 34D — 3D Product Integration Acceptance

Status: **COMPLETE**

Phase 34D connects the accepted Phase 34C PBR worker to the authenticated AIOS product surface and the `ai.vip-e.net` user portal. It does not weaken the Super Owner boundary introduced in Phase 34B: 3D is Owner-managed, defaults to the highest current public plan (`business`), and requires the `3d.generation` entitlement unless the Super Owner applies an explicit user override.

## Product contract

- Authenticated, project-scoped API supports access status, create, list/status, cancel, clarification/replacement image, and protected artifact links.
- Project access is organization-isolated and additionally requires project ownership/membership plus the normal project read/write permission.
- The database persists durable 3D jobs, provider lifecycle state, audit events, metering state, and artifact metadata in Alembic revision `20260809_0013`.
- A dedicated production `three-d-worker` claims jobs with leases, securely reads RunPod credentials from the external `0600` secret, submits the full PBR pipeline, polls/cancels/retries within Owner limits, validates GLB magic/hash/PBR manifest, persists the artifact, meters usage idempotently, and removes the private source image after terminal processing.
- Shape-only fallback is disabled for product generation. A successful product artifact must report `fallback_used=false`.

## Super Owner policy

The `/owner/3d` control plane owns service enablement, eligible plans, entitlement, explicit user allow/deny lists, concurrency, queue/runtime/retry limits, per-job/daily/monthly spend ceilings, alert threshold, monthly generation quota, input size, texture resolution, artifact retention, signed-link lifetime, and GLB compression policy.

The production-safe default queue allowance is `1200` seconds. Live acceptance measured a cold-start/provider delay of `383788 ms`; the former `300` second default could terminate a valid cold start before the worker became ready. The Super Owner can change this value up to the enforced policy ceiling.

## Private object storage

The configured production S3 bucket is private and uses server-side encryption. Public Access Block is enabled. Phase 34D configured CORS only for `https://ai.vip-e.net` and only for `GET`/`HEAD`, enabling the browser-based Three.js viewer without making objects public.

Object keys are tenant/project/job scoped. The API returns short-lived SigV4 URLs for inline preview and download only after authenticated authorization and current 3D eligibility are rechecked. A live presigned `Range` request from the portal origin returned the expected GLB bytes and CORS header. Temporary acceptance objects were deleted after verification.

## Live end-to-end acceptance

A clean isolated AIOS Business tenant/project was migrated through `20260809_0013`, a real source image was stored privately, and the Phase 34D worker processed the durable database job through the production RunPod Serverless endpoint.

Accepted live result:

- Job state: `completed`, progress `100`, one attempt, metering `metered`.
- RunPod provider delay: `383788 ms`.
- RunPod execution time: `169760 ms`.
- Metered GPU runtime estimate recorded by AIOS: `0.033952 USD` under the configured conservative rate.
- Final artifact: `2,734,648` bytes, valid binary glTF (`glTF` magic).
- SHA-256: `0a62143b4bd72ecce5ddb5e85bb4a420fcdbe0c11cdff67c56c2428b51a6648e`.
- PBR validation: `1` PBR material, `2` embedded textures, `fallback_used=false`.
- S3 round-trip size and SHA-256 matched database metadata exactly.
- The private input object was deleted after completion.
- Billing recorded exactly one idempotent `3d_generations` usage event for the accepted job.
- Durable audit records and user/owner lifecycle notifications were persisted; normal API submission also emits the initial queued notification.
- The current endpoint finished with no queued or in-progress jobs and no running or unhealthy worker. FlashBoot may retain an idle/ready cached worker state while running GPU count is zero.

The RunPod template is pinned to the currently resolvable immutable Docker Hub OCI manifest digest:

`sha256:34bd37c577a8c769005a11f94bf4658d0b9f31d52df5c75e2a8f01a5ed8499dc`

During Phase 34D acceptance, the previously documented manifest digest no longer resolved from Docker Hub and caused new workers to become unhealthy. The template and tracked runtime documentation were corrected to the resolvable immutable digest, and fresh live generation then passed. Stale test/production endpoints were deleted after the corrected endpoint passed. The active endpoint identifier remains external runtime configuration in the protected RunPod secret file and is not committed.

## User portal

The Projects UI now includes an Owner-gated 3D panel with six-locale copy, source image validation, owner-defined quota/limits, texture resolution selection, live job polling and progress, cancellation, replacement-image clarification, secure link renewal, GLB download, and an interactive Three.js `GLTFLoader` + `OrbitControls` preview. Renderer, controls, geometries, materials, and textures are disposed when the preview changes/unmounts.

## Acceptance boundary

Phase 34D is accepted only because the product path, database migration, private storage, live provider execution, metering, notifications/audit, signed browser preview, portal build, and owner/user authorization contracts all passed. Security/observability/resilience hardening beyond these product-integration requirements belongs to Phase 34E, and license/region/provider-policy gates remain Phase 34F.
