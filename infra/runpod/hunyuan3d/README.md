# AIONEX Hunyuan3D RunPod Serverless runtime

## Current status: quarantined; not approved for production

The historical Phase 34C image below is **security quarantined**. The
source-controlled gate
[`HUNYUAN_RUNTIME_SECURITY_APPROVED`](../../../web-dashboard/backend/app/services/three_d_provider_policy.py)
is `False`, and the deployed AIOS backend independently reported the same
quarantine during the 2026-10-17 NEW-host review. Do not activate, submit work to,
or describe this digest as an approved production image.

- Historical tag: `ipdomx/aionex-hunyuan3d:phase34c-pbr-v11`
- Quarantined immutable digest: `sha256:34bd37c577a8c769005a11f94bf4658d0b9f31d52df5c75e2a8f01a5ed8499dc`

Changing an Owner setting or relying on the earlier functional acceptance does
not clear this source-controlled security gate. FR-16D requires a rebuilt image,
fresh security evidence and functional acceptance before any later activation.
A source change, successful image build, or historical scan alone is not that
acceptance. The current review did not rebuild, scan or activate a GPU image.

The existing TripoSR route is separately governed by its own configuration,
eligibility, quota and disclosure checks. Its local runtime configuration was
present on NEW; this observation is not a fresh provider-health or generation
test and does not establish Hunyuan PBR capability. See the
[FR-16A current runtime inventory](../../../docs/project/receipts/FR16A-current-2d-3d-runtime-20261017.md).

## Historical Phase 34C pipeline

`image -> Hunyuan3D shape -> Hunyuan3D Paint PBR -> Blender cleanup -> glTF Transform optimize/inspect -> validated GLB`

The worker requires albedo, metallic, and roughness outputs, packs metallic/roughness into the glTF PBR material, verifies mesh/material/texture presence, emits SHA-256 and stage timings, and fails closed when the PBR path fails. Shape-only fallback is permitted only when `allow_shape_fallback=true` is explicitly supplied by governing policy.

## Historical endpoint settings

These settings record the earlier deployment. They are not instructions to
reactivate the quarantined digest, and the current review did not query the
RunPod control plane.

- Container image: immutable digest recorded above.
- Container disk: 100 GB.
- Container start command / Docker command override: empty.
- Docker entrypoint override: empty.
- `RUNPOD_INIT_TIMEOUT=1800`.
- Serverless endpoint: min workers 0, max workers 1, idle timeout 5 seconds, GPU count 1, execution timeout 3600 seconds.

Do not commit API keys, endpoint IDs, model caches, generated GLBs, runtime logs, or cloned third-party repositories here.

## Historical functional evidence

Phase 34C live acceptance produced a non-fallback textured/PBR GLB of 2,734,648 bytes from a 4,139,332-byte pre-optimization artifact. Two identical seeded acceptance runs produced the same SHA-256: `0a62143b4bd72ecce5ddb5e85bb4a420fcdbe0c11cdff67c56c2428b51a6648e`.

That evidence remains historical and does not supersede the later quarantine or
prove current NEW-host release acceptance.
