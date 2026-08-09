# AIONEX Hunyuan3D RunPod Serverless runtime

Phase 34C known-good production image:

- Tag: `ipdomx/aionex-hunyuan3d:phase34c-pbr-v11`
- Immutable digest: `sha256:34bd37c577a8c769005a11f94bf4658d0b9f31d52df5c75e2a8f01a5ed8499dc`

The production RunPod template must use the immutable digest rather than a mutable tag.

## Pipeline

`image -> Hunyuan3D shape -> Hunyuan3D Paint PBR -> Blender cleanup -> glTF Transform optimize/inspect -> validated GLB`

The worker requires albedo, metallic, and roughness outputs, packs metallic/roughness into the glTF PBR material, verifies mesh/material/texture presence, emits SHA-256 and stage timings, and fails closed when the PBR path fails. Shape-only fallback is permitted only when `allow_shape_fallback=true` is explicitly supplied by governing policy.

## Required RunPod settings

- Container image: pinned digest above.
- Container disk: 100 GB.
- Container start command / Docker command override: empty.
- Docker entrypoint override: empty.
- `RUNPOD_INIT_TIMEOUT=1800`.
- Serverless endpoint: min workers 0, max workers 1, idle timeout 5 seconds, GPU count 1, execution timeout 3600 seconds.

Do not commit API keys, endpoint IDs, model caches, generated GLBs, runtime logs, or cloned third-party repositories here.

Phase 34C live acceptance produced a non-fallback textured/PBR GLB of 2,734,648 bytes from a 4,139,332-byte pre-optimization artifact. Two identical seeded acceptance runs produced the same SHA-256: `0a62143b4bd72ecce5ddb5e85bb4a420fcdbe0c11cdff67c56c2428b51a6648e`.
