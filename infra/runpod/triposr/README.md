# AIONEX TripoSR fallback worker

Commercially permissive fallback for jurisdictions where Tencent Hunyuan3D 2.1 is not licensed or when Owner policy disables the primary provider. The vendored source is pinned to TripoSR commit `107cefdc244c39106fa830359024f6a2f1c78871`; the model snapshot is pinned to Hugging Face revision `5b521936b01fbe1890f6f9baed0254ab6351c04a`. Both upstream source and model card identify the license as MIT. The MIT license is retained under `vendor/LICENSE`.

This fallback returns a valid GLB using TripoSR vertex colors. It is not represented as Hunyuan PBR output; the response manifest explicitly reports `fallback_used=true`, `fallback_provider=triposr`, and `pbr_material_count=0`.

## FR-16D hardening

- `requirements.txt` holds the direct pins (Dependabot updates it). `requirements.lock`
  is the hash-locked closure installed with `--require-hashes --no-deps`; the build
  then runs `pip install --no-index -r requirements.txt`, so a pin change without a
  regenerated lock fails the image build. Regenerate with:
  `uv pip compile requirements.txt -c base-constraints.txt --generate-hashes --python-version 3.11 --python-platform x86_64-manylinux_2_28 --no-annotate -o requirements.lock`,
  where `base-constraints.txt` pins the torch/CUDA/sympy/networkx/jinja2/filelock versions of the base image.
- `fetch_models.py` downloads the pinned TripoSR model, DINO config and u2net with SHA-256
  checks and converts `model.ckpt` to safetensors; `torch.load` and Hub downloads are
  disabled at runtime. The container runs as a non-root user.
