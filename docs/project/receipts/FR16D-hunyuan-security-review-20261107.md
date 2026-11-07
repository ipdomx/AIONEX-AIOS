# FR-16D: Hunyuan3D security review and hardened rebuild (2026-11-07)

Status: **source, image definitions and CI gate are in the PR. Deploy and the live GPU test are not done.**
`HUNYUAN_RUNTIME_SECURITY_APPROVED` stays `False` in
`web-dashboard/backend/app/services/three_d_provider_policy.py`. Lifting it is
owner decision O-10 in the pre-launch register, and it comes only after T-18.

Scope: code, images and docs. No server access, no RunPod calls, no deploys,
no paid GPU work. The upstream source was audited with read-only clones on
GitHub-hosted runners. Upstream commit `82920d643c0dc2f7bfd7255f45f62d386edfe60c`
is the same commit as `HUNYUAN_LICENSE_SOURCE_COMMIT`.

## 1. Why the image was quarantined

The quarantine record is P36-0022 in
`docs/phase-36/PHASE_36_UNIVERSAL_CAPABILITY_SCALE_MASTER_ROADMAP.md` and
`docs/phase-36/receipts/36N-2026-08-30-comprehensive-closeout.md`. Trivy 0.73.0
scanned the exact production digest
`sha256:34bd37c5…99dc` (`phase34c-pbr-v11`) and found **33 Critical / 590 High**.

- **OS:** the image inherited an old general-purpose RunPod development base
  with SSH, Nginx, Jupyter, compilers and `linux-libc-dev`. `linux-libc-dev`
  alone accounted for 501 of the High/Critical findings.
- **Active inference venv:** `/opt/hunyuan-venv` had 35 High/Critical findings
  of its own, so the reviewers refused to wave them through with VEX. They
  include:
  - Critical `torch 2.5.1+cu124` (CVE-2025-32434, the `torch.load`
    `weights_only` bypass)
  - Critical and High `pytorch-lightning 1.9.5` (CVE-2024-8019/8020 LightningApp,
    CVE-2026-31221 checkpoint load)
  - High findings in Pillow, Transformers (CVE-2026-4372, CVE-2026-5241: remote
    repository/config loading), Cryptography, Gradio, Starlette, Diffusers and
    Protobuf.

The 2026-08-31 candidate removed packages from the same base and justified the
remaining 8 High/Critical with `openvex.json`. It still did not earn approval.

This review found further causes in the image definition and the upstream code:

| # | Finding | Where |
|---|---|---|
| F1 | **Opaque, unreviewed base.** Everything was layered on `ipdomx/aionex-hunyuan3d@sha256:e4220d58…`, a private image with no source in the repo. It shipped files that are not in upstream at the reviewed commit, for example the top-level `torchvision_fix` module the old handler imported. Its torch, CUDA and Python stack could not be reproduced or reviewed. | old `Dockerfile` line 2 |
| F2 | **Unpinned remote script as root.** `curl -fsSL https://deb.nodesource.com/setup_22.x \| bash -`, then a global `npm install` with no lockfile. | old `Dockerfile` |
| F3 | **Upstream dependency hygiene.** `requirements.txt` adds `--extra-index-url` for the Tencent and Aliyun PyPI mirrors (dependency-confusion risk) and leaves `timm`, `pythreejs`, `torchdiffeq` and `deepspeed` unpinned. It also pulls the demo/server stack (`gradio`, `fastapi`, `uvicorn`), `bpy==4.0`, `cupy`, `open3d` and the training stack (`pytorch-lightning`, `basicsr`/`realesrgan` → `tb-nightly`, `lmdb`). No hashes. | upstream `requirements.txt` |
| F4 | **Pickle checkpoints at runtime.** The shape DiT/VAE (`model.fp16.ckpt`) and the paint text encoder, UNet and VAE (`*.bin`) are torch pickle files. Real-ESRGAN `RealESRGAN_x4plus.pth` is loaded by `realesrgan` with a plain `torch.load`, which can also download from a URL. On old torch that is arbitrary code execution, and it is the same class as CVE-2025-32434. | `pipelines.py`, `unet/modules.py`, `basicsr/realesrgan` |
| F5 | **Runtime Hub fetches of code and weights.** `multiview_utils.py` calls `huggingface_hub.snapshot_download(repo_id=...)` and `smart_load_model` falls back to `snapshot_download`. Diffusers `custom_pipeline` and the `["modules", "UNet2p5DConditionModel"]` component in `model_index.json` make Diffusers import Python (`unet/modules.py`, `attn_processor.py`) **from the model snapshot directory**. That is remote code execution through the weights repo, with no `trust_remote_code` prompt. Dino and Hunyuan ids defaulted to Hub names. | upstream paint code and model repo |
| F6 | **Shell-outs and dead servers in the tree.** `gradio_app.py` (`os.system`, `pip install` at runtime), `api_server.py`, `model_worker.py`, and `postprocessors.MeshSimplifier` (`os.system` on a prebuilt `mesh_simplifier.bin`). | upstream |
| F7 | **Weak request handling.** No size, type or pixel-count limit on the input image (decompression bomb), unchecked `int()` casts, no output size cap, no job deadline, work directories never deleted, and the container ran as root. | old `handler.py` |

The weights are only partly pinned. DINO was pinned to a revision. The Hunyuan
shape and paint weights were baked into the opaque base and cannot be verified.

## 2. Mitigations in this PR

| Finding | Mitigation |
|---|---|
| F1 | The new `infra/runpod/hunyuan3d/Dockerfile` builds from public `pytorch/pytorch:2.10.0-cuda12.8-cudnn9-{devel,runtime}` (Ubuntu 24.04, Python 3.12) by immutable digest. torch 2.10.0 fixes CVE-2026-24747, which the first CI scan of a 2.9.1 base flagged. The base image's `uv` (GHSA-hq85-5cpj-mr62, CRITICAL), `wheel` and `setuptools` (its vendored wheel 0.45.1 carries CVE-2026-24049) are uninstalled from the runtime. Hunyuan source is fetched by commit and checked with `git rev-parse HEAD`. Nothing comes from the old base. |
| F2 | Blender 5.2.3 and Node v24.22.2 come from official tarballs checked against their published SHA-256. `gltf-transform` and `sharp` are installed with `npm ci --ignore-scripts` from a committed `package-lock.json` (sha512 integrity). npm and corepack are removed afterwards. |
| F3 | Curated runtime set in `requirements.in`, compiled to `requirements.lock` (3,590 hashes). It uses Transformers 5.22.2 and Diffusers 0.42.1, because Transformers 4.x carries CVE-2026-4372, CVE-2026-5241, CVE-2026-9856 and CVE-2026-80047. It also pins Pillow 13.0.0, msgpack 1.2.4 and soupsieve 4.0.1 over the base image's vulnerable copies. The lock is installed with `--require-hashes --no-deps --no-build-isolation`, followed by `pip check`. There are no extra indexes. Removed from the image: gradio, fastapi demo, deepspeed, open3d, cupy, bpy (pip), pytorch-lightning, basicsr, realesrgan, tb-nightly, rembg and onnxruntime. The pybind11 build dependency is hash-locked separately. |
| F4 | `fetch_weights.py` runs in a throwaway build stage. It downloads each file from an immutable revision URL and checks size and SHA-256 against `weights.lock.json` (Hunyuan `0b94677654c57bb9a6b6845cd7b704ccf551d327`, DINOv2 `611a9d42…`, Real-ESRGAN v0.1.0). Each pickle is loaded once with `torch.load(weights_only=True)` (restricted unpickler), saved as safetensors and deleted. The final tree is scanned for pickle streams, torch-zip checkpoints and `.py` files. Code is patched to load safetensors only: `use_safetensors=True` for shape, a safetensors UNet loader, and Diffusers/Transformers `use_safetensors`. A reviewed `overrides/image_super_utils.py` (RRDBNet, Apache-2.0 attribution) replaces basicsr/realesrgan. At runtime `torch.load`, `torch.hub` and the Hub download helpers raise immediately. |
| F5 | `patch_hunyuan_runtime.py` (every patch must match exactly or the build fails) makes three changes. The paint path must be a baked local directory. The vendored `HunyuanPaintPipeline` and `UNet2p5DConditionModel` classes are constructed explicitly with `local_files_only=True`, so Diffusers never imports code from the model directory. Model ids default to `/models/...`. `weights.lock.json` never fetches `.py` files. The model-repo copies of `unet/modules.py` and `attn_processor.py` were confirmed byte-identical to the reviewed GitHub files (`664983…`, `a41bf0…`). The post-condition rejects any `trust_remote_code=True`. Offline env vars (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `DIFFUSERS_OFFLINE`) are set in both the image and the handler. |
| F6 | The patch deletes demo, server and training files, the visualizers and the simplifier binary. `MeshSimplifier`'s shell call is replaced with a hard error. The post-condition rejects any remaining `os.system`, `subprocess`, `pickle.load(s)` or `snapshot_download` (except the offline-guarded `smart_load_model`). |
| F7 | `input_guard.py` (shared byte-for-byte with TripoSR, enforced by CI) checks: base64 ≤ 16 MiB, decoded ≤ 12 MiB, PNG/JPEG/WebP only, a single frame, ≤ 16.7 MP and ≥ 64 px with the Pillow bomb warning turned into an error, and no unknown fields. The handler adds typed and bounded `seed`/`texture_size`/policy, a ≤ 100 MiB output cap, a 3,000 s job deadline, timeouts on every subprocess, per-job private temp directories that are always deleted, and Blender with `--factory-startup --disable-autoexec --offline-mode`. The container runs as non-root uid 10001 with pip, setuptools and wheel removed. |

CI: `.github/workflows/fr16d-3d-runtime-container-security.yml` does three things:

1. Validates the pins, hashes and weights lock.
2. Builds `--target runtime` (code and locked dependencies, no weights) on a
   GitHub runner. The build runs the hardened import contract: torch.load guard,
   early request rejection, Hunyuan, paint, UNet, super-resolution and
   custom_rasterizer imports.
3. Runs the repository gate: CycloneDX SBOM (syft 1.50.0) plus Trivy 0.72.0
   failing on any HIGH or CRITICAL, unfixed included, with no VEX.

The `release` target adds only `/models`, which holds safetensors and JSON,
then rechecks `MANIFEST.sha256`. The scanned package inventory is therefore the
same. `openvex.json` belongs to the retired 2026-08-31 candidate. The new gate
does not use it.

## 3. Residual risk

1. **No functional evidence yet.** The CUDA extensions are compiled for sm_80
   to sm_90 and the Diffusers/Transformers versions are newer than the Phase 34C
   acceptance. The patched loaders have only been checked by imports, not run
   against weights. A real non-fallback PBR run on a GPU is required (T-18)
   before anyone may call this image functional.
2. **One-time restricted unpickling at build time.** It uses
   `weights_only=True` on SHA-256-pinned files in a stage that is thrown away.
   That is a much smaller exposure than runtime pickle, but it is not zero.
3. **Network.** The RunPod SDK needs egress, so network access cannot be
   removed from the container. "No runtime network for code" is enforced
   in-process (offline flags plus guards), not by the kernel.
4. **Locked versions age.** Future CVEs will fail the CI gate. That is the
   intended behaviour. Regenerate the locks with the commands in
   `requirements.in` and the TripoSR README, then rebuild.
5. **Licence.** The Tencent Hunyuan 3D Community License territory rules stay
   enforced by `three_d_provider_policy.py`. This review does not change them.

## 4. Deploy steps for the pre-launch window (T-18, then O-10)

1. Build on a builder with at least 120 GB of free disk and egress to Docker
   Hub, GitHub, huggingface.co, download.blender.org, nodejs.org and npm:
   `docker build --pull --target release -t ipdomx/aionex-hunyuan3d:fr16d-<git-sha> infra/runpod/hunyuan3d`.
   It must print `Hunyuan hardened runtime contract: PASS`,
   `model assets verified` and `model manifest verified`.
2. Scan the exact image the same way CI does:
   `trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed=false`.
   Generate a CycloneDX SBOM. Record both report SHA-256 values.
3. Push the image and record the immutable digest:
   `docker push …` then `docker buildx imagetools inspect …`.
4. On RunPod, create a **new** template pinned to the digest. Do not reuse
   `dyb5ilmo0l`, the template of the quarantined v11 image. Settings: container
   disk ≥ 60 GB, no start-command override, `RUNPOD_INIT_TIMEOUT=1800`,
   1 GPU (≥ 24 GB, sm_80 or newer), execution timeout 3,600 s, workers min 0 and
   max 1, idle timeout 5 s, **US data centres only** (the backend checks
   `dataCenterIds`). Create or update the endpoint, then put its ID and
   `RUNPOD_HUNYUAN_LOCATION=US` into the protected `RUNPOD_GPU.env`. Keep the
   API key out of git.
5. Live acceptance needs the owner's cost approval (O-08) and calls the
   endpoint directly with `allow_shape_fallback=false`. Repeat the Phase 34C
   checks:
   - non-fallback PBR GLB
   - glTF binary, mesh, material and texture validation
   - ≥ 1 PBR material
   - Blender and glTF Transform stages
   - SHA-256 recorded
   - two runs with the same seed are byte-identical
   - no queued or in-progress jobs afterwards
   - `running=0`

   Also send a negative request (an oversized image and an unknown field) and
   confirm it is rejected before GPU work.
6. Write a receipt with the digest, scan hashes, job IDs, timings and output
   hashes. Only then may the owner decide O-10: set
   `HUNYUAN_RUNTIME_SECURITY_APPROVED = True`, replace
   `HUNYUAN_QUARANTINED_IMAGE_DIGEST` with the retired digest list in a
   protected PR, and deploy the backend. Rollback is to flip the constant back,
   which fails the route closed so TripoSR keeps serving.

## 5. TripoSR (same hardening where it applies)

- Folds in the Dependabot bumps msgpack 1.2.1→1.2.3 (#1005), Brotli
  1.2.0→1.2.1 (#971) and Pillow 12.3.0→13.0.0 (#952).
- Supersedes rembg 2.0.82 (#1006) with rembg 2.0.87. The CI gate found
  CRITICAL Pillow 12.x CVEs (for example CVE-2026-112393), and rembg 2.0.82
  caps Pillow below 13.
- Moves the base to torch 2.10.0 (CVE-2026-24747) and removes the base
  image's `uv`.
- Adds a hash-locked `requirements.lock` (3,707 hashes). It is installed with
  `--require-hashes`, then an offline `--no-index` install proves that
  `requirements.txt` matches the lock.
- `fetch_models.py` fetches the TripoSR model, DINO config and u2net with
  pinned revisions and SHA-256, and converts `model.ckpt` to safetensors. This
  replaces the unverified `snapshot_download`.
- Also adds runtime guards, the shared `input_guard.py`, an output cap,
  temp-directory cleanup and a non-root user.
- The existing TripoSR SBOM step failed on every Dependabot PR with
  `disk quota exceeded` under `/tmp`. Syft now uses the runner temp directory.

## 6. Blender (roadmap 2.4, related)

The pinned Blender 5.2.3 also powers the new `three-d-converter` sidecar.

- The sidecar has no network (`network_mode: none`), a read-only root, drops
  all capabilities and runs as a non-root user.
- The three-d-worker sends it each generated GLB through a spool. It returns
  OBJ, FBX, USDZ and a PNG preview.
- Each conversion runs under a timeout that kills the process group, with
  rlimits on address space, CPU, file size, open files and core dumps.
- Private HOME/config/script directories, factory startup, no autoexec and an
  in-process socket guard apply to every run.
- Inputs are validated (GLB structure, no external URIs, texture-dimension and
  pixel-budget bomb limits) and outputs are validated again (magic bytes,
  sizes, USDZ root layer, preview size) before storage.
- Users only see formats that were stored for that artifact. Without the
  sidecar, nothing beyond the GLB and the in-browser OBJ is offered.
- CI scan of the converter image: Ubuntu 24.04 with **0 HIGH/CRITICAL**, and
  the conversion contract passes at build time.

Deploy is T-19.
