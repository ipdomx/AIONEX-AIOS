# Hunyuan3D production endpoint — Phase 34B

- Template: `1e0hug1c4t`
- Image: `ipdomx/aionex-hunyuan3d:phase33-lazy2` (pin digest in build/release metadata)
- Active workers / workersMin: `0`
- Max workers / workersMax: `1`
- Idle timeout: `5s`
- Execution timeout: `1800s`
- Init timeout: `RUNPOD_INIT_TIMEOUT=1800`
- Container start override: none
- Production endpoint ID is runtime configuration and is stored only in protected `RUNPOD_GPU.env`.

Acceptance requires a real image-to-GLB job, `glTF` binary magic validation, no queued/in-progress jobs afterwards, and `running=0` without deleting the endpoint. RunPod FlashBoot may report cached `idle/ready` worker state after compute has scaled down; per RunPod lifecycle documentation, `Idle` is not billed.
