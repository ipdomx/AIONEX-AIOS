# Hunyuan3D production endpoint — Phase 34C

- Template: `dyb5ilmo0l`
- Image tag: `ipdomx/aionex-hunyuan3d:phase34c-pbr-v11`
- Image digest: `sha256:34bd37c577a8c769005a11f94bf4658d0b9f31d52df5c75e2a8f01a5ed8499dc`
- The RunPod template is pinned to the immutable digest.
- Active workers / workersMin: `0`
- Max workers / workersMax: `1`
- Idle timeout: `5s`
- Execution timeout: `3600s`
- Init timeout: `RUNPOD_INIT_TIMEOUT=1800`
- Container start override: none
- Production endpoint ID is runtime configuration and is stored only in protected `RUNPOD_GPU.env`.

Phase 34C acceptance requires a real image-to-textured/PBR-GLB job with fallback disabled, `glTF` binary validation, PBR material/texture validation, Blender post-processing, glTF Transform optimization/inspection, SHA-256 integrity, deterministic repeat acceptance, no queued/in-progress jobs afterwards, and `running=0` without deleting the production endpoint.

The accepted production test vector produced a 2,734,648-byte final GLB from a 4,139,332-byte pre-optimization artifact with one PBR material and two embedded textures. Two same-seed runs were byte-identical with SHA-256 `0a62143b4bd72ecce5ddb5e85bb4a420fcdbe0c11cdff67c56c2428b51a6648e`.
