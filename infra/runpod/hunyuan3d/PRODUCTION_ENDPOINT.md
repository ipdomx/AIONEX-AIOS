# Hunyuan3D historical production endpoint — Phase 34C

## Current status: image quarantined

The image in this record is **not approved for production**.
[`HUNYUAN_RUNTIME_SECURITY_APPROVED`](../../../web-dashboard/backend/app/services/three_d_provider_policy.py)
is `False` in the reviewed source and the deployed backend. The 2026-10-17
review verified that both identify the digest below as quarantined. Preserve
the record as historical evidence; do not use it to activate a worker or submit
a job.

FR-16D must resolve the quarantine through a rebuilt, independently reviewed
image with fresh security and functional acceptance. No such acceptance is
claimed here. See the [current inventory](../../../docs/project/receipts/FR16A-current-2d-3d-runtime-20261017.md).

## Recorded configuration

The values below describe the earlier Phase 34C deployment. The current review
did not query RunPod, so they are not a current control-plane attestation.

- Template: `dyb5ilmo0l`
- Historical image tag: `ipdomx/aionex-hunyuan3d:phase34c-pbr-v11`
- Quarantined image digest: `sha256:34bd37c577a8c769005a11f94bf4658d0b9f31d52df5c75e2a8f01a5ed8499dc`
- The historical RunPod template was pinned to this immutable digest.
- Recorded active workers / workersMin: `0`
- Recorded max workers / workersMax: `1`
- Idle timeout: `5s`
- Execution timeout: `3600s`
- Init timeout: `RUNPOD_INIT_TIMEOUT=1800`
- Container start override: none
- Production endpoint ID is runtime configuration and is stored only in protected `RUNPOD_GPU.env`.

## Historical functional acceptance

Phase 34C acceptance required a real image-to-textured/PBR-GLB job with fallback disabled, `glTF` binary validation, PBR material/texture validation, Blender post-processing, glTF Transform optimization/inspection, SHA-256 integrity, deterministic repeat acceptance, no queued/in-progress jobs afterwards, and `running=0` without deleting the production endpoint.

The accepted historical test vector produced a 2,734,648-byte final GLB from a 4,139,332-byte pre-optimization artifact with one PBR material and two embedded textures. Two same-seed runs were byte-identical with SHA-256 `0a62143b4bd72ecce5ddb5e85bb4a420fcdbe0c11cdff67c56c2428b51a6648e`.

This earlier functional result does not clear the later security quarantine.
