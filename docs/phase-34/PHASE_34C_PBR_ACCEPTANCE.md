# Phase 34C — Full Textured/PBR Pipeline Acceptance

Status: **COMPLETE**

Phase 34C upgrades the Phase 33 shape-only worker into a fail-closed, full textured/PBR production pipeline.

## Runtime contract

- Shape: Hunyuan3D 2.1 shape pipeline.
- Texture/PBR: Hunyuan3D Paint PBR with baked local model assets.
- Post-processing: Blender mesh cleanup, transform application, normal repair, and smooth shading.
- Delivery optimization: glTF Transform 4.4.2 optimize + inspect.
- Default compatibility policy: no required geometry compression extension; textures are bounded by the requested maximum size.
- Optional `meshopt` policy is explicit.
- Shape-only fallback is disabled by default and can occur only when `allow_shape_fallback=true` is explicitly supplied by the governing policy.
- Every final artifact is checked for GLB magic, PBR material/texture presence, size, and SHA-256 integrity.
- A fixed generation seed is recorded in the manifest.

## Production image

- Tag: `ipdomx/aionex-hunyuan3d:phase34c-pbr-v11`
- Immutable digest: `sha256:34bd37c577a8c769005a11f94bf4658d0b9f31d52df5c75e2a8f01a5ed8499dc`
- RunPod template is pinned to the immutable digest rather than a mutable tag.
- `RUNPOD_INIT_TIMEOUT=1800`.
- Container disk: 100 GB.
- Production endpoint: workersMin=0, workersMax=1, idleTimeout=5 seconds, executionTimeout=3600 seconds.
- The endpoint identifier is runtime configuration and remains only in the protected production secret file.

## Live acceptance evidence

A real RunPod GPU job completed without fallback using the repository demo image and the following explicit contract:

- `allow_shape_fallback=false`
- seed `12345`
- texture limit `1024`
- compression policy `compat`
- final artifact: `final.glb`
- pre-optimization size: `4,139,332` bytes
- post-optimization size: `2,734,648` bytes
- optimization ratio: `0.660650`
- mesh count: `1`
- material count: `1`
- PBR material count: `1`
- embedded texture count: `2`
- generated albedo bytes: `557,252`
- generated metallic bytes: `241,789`
- generated roughness bytes: `465,657`
- generated packed metallic-roughness bytes: `1,685,880`
- SHA-256: `0a62143b4bd72ecce5ddb5e85bb4a420fcdbe0c11cdff67c56c2428b51a6648e`
- fallback used: `false`

Measured first-run stage timings:

- shape: `92.675s`
- texture/PBR: `84.043s`
- Blender: `1.729s`
- glTF Transform: `1.169s`
- total worker pipeline: `180.756s`

`gltf-transform inspect` confirmed one triangle mesh, a `PBR_Material` using both `baseColorTexture` and `metallicRoughnessTexture`, and two embedded 1024×1024 PNG textures. An independent Blender import of the accepted final GLB confirmed one mesh, one material, two images, 22,958 vertices, and 40,000 polygons.

## Deterministic acceptance

The exact same input, seed, texture limit, fallback policy, and compression policy were executed a second time on the same production image. The second run completed without fallback and produced exactly the same:

- artifact size: `2,734,648` bytes
- structural counts
- optimization ratio
- SHA-256: `0a62143b4bd72ecce5ddb5e85bb4a420fcdbe0c11cdff67c56c2428b51a6648e`

This proves bit-for-bit repeatability for the accepted Phase 34C test vector while retaining SHA-256 verification for every generated artifact.

## Scale-to-zero acceptance

After the two acceptance jobs, the production endpoint reported:

- queued jobs: `0`
- in-progress jobs: `0`
- running workers: `0`
- unhealthy workers: `0`

No validation endpoint is retained separately from the promoted production endpoint.

## Failure history closed during acceptance

The live validation exposed and closed all discovered runtime blockers before acceptance: RunPod queue pickup mode, torchvision `functional_tensor` compatibility, RealESRGAN checkpoint working-directory resolution, `pkg_resources`/setuptools availability, preservation of the real renderer `mesh_utils` API while avoiding in-process Blender coupling, and Blender's NumPy dependency.

## Definition of done

Phase 34C is complete only with a real non-fallback PBR artifact, Blender and glTF Transform success, PBR material/texture validation, deterministic repeat acceptance, immutable image pinning, zero queued/in-progress jobs, and zero running GPU workers. All conditions above are satisfied by this acceptance record.
