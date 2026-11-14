"""Build-time hardening patches for the pinned Hunyuan3D-2.1 source (FR-16D).

Applied once to upstream commit 82920d643c0dc2f7bfd7255f45f62d386edfe60c.
Every patch must match exactly; a missing target fails the image build so an
upstream drift can never silently skip a security patch.

Usage: python patch_hunyuan_runtime.py [ROOT]   (default /opt/Hunyuan3D-2.1)
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/Hunyuan3D-2.1")
OVERRIDES = Path(__file__).resolve().parent / "overrides"

# Demo servers, training code and helpers that shell out; none are part of the
# serverless inference path and several start network services or run
# os.system/subprocess.
REMOVE = (
    "gradio_app.py",
    "demo.py",
    "model_worker.py",
    "api_server.py",
    "api_models.py",
    "constants.py",
    "test_api_server.py",
    "hy3dshape/main.py",
    "hy3dshape/minimal_demo.py",
    "hy3dshape/minimal_demo_with_ckpt.py",
    "hy3dshape/minimal_vae_demo.py",
    "hy3dshape/hy3dshape/data",
    "hy3dshape/hy3dshape/utils/trainings",
    "hy3dshape/hy3dshape/utils/visualizers",
    "hy3dshape/hy3dshape/rembg.py",
    "hy3dshape/hy3dshape/mesh_simplifier.bin",
    "hy3dpaint/train.py",
    "hy3dpaint/src",
    "hy3dpaint/hunyuanpaintpbr/unet/model.py",
    "hy3dpaint/utils/torchvision_fix.py",
)


def sub(path: str, pattern: str, replacement: str, *, count: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    updated, found = re.subn(pattern, replacement, text, count=count, flags=re.MULTILINE)
    if found != count:
        raise SystemExit(f"patch target missing in {path}: {pattern!r} ({found}/{count})")
    target.write_text(updated, encoding="utf-8")


def patch_dinov2_v5_names() -> None:
    """transformers 5 renamed the Dinov2 attention projections; the pinned DiT
    checkpoint still carries the 4.x names for its image conditioner. Remap them
    (only when the installed module uses the new names) so the conditioner keeps
    loading strictly. Found by the T-18 CPU load check on 2026-11-13."""
    sub(
        "hy3dshape/hy3dshape/pipelines.py",
        r"^(\s*)conditioner\.load_state_dict\(ckpt\['conditioner'\]\)\n",
        "\\1conditioner.load_state_dict(_aionex_remap_dinov2(ckpt['conditioner'], conditioner.state_dict().keys()))\n",
    )
    sub(
        "hy3dshape/hy3dshape/pipelines.py",
        r"^(def retrieve_timesteps\()",
        "_AIONEX_DINOV2_V5 = (\n"
        "    ('.attention.attention.query.', '.attention.q_proj.'),\n"
        "    ('.attention.attention.key.', '.attention.k_proj.'),\n"
        "    ('.attention.attention.value.', '.attention.v_proj.'),\n"
        "    ('.attention.output.dense.', '.attention.o_proj.'),\n"
        ")\n\n\n"
        "def _aionex_remap_dinov2(state, expected_keys):\n"
        "    if any('.attention.attention.' in key for key in expected_keys):\n"
        "        return state\n"
        "    remapped = {}\n"
        "    for key, value in state.items():\n"
        "        for old, new in _AIONEX_DINOV2_V5:\n"
        "            if old in key:\n"
        "                key = key.replace(old, new, 1)\n"
        "                break\n"
        "        remapped[key] = value\n"
        "    return remapped\n\n\n"
        "\\1",
    )


def main() -> None:
    # 1. Paint model: local, pinned snapshot only; explicit vendored classes, so
    #    Diffusers never imports code from the model directory or the Hub, and
    #    every component loads from safetensors.
    sub(
        "hy3dpaint/utils/multiview_utils.py",
        r"^(\s*)model_path = huggingface_hub\.snapshot_download\(\s*repo_id=config\.multiview_pretrained_path,\s*allow_patterns=\[\"hunyuan3d-paintpbr-v2-1/\*\"\],\s*\)\n",
        "\\1if not os.path.isdir(config.multiview_pretrained_path):\n"
        "\\1    raise RuntimeError(\"Hunyuan paint weights must be a baked local directory\")\n"
        "\\1model_path = config.multiview_pretrained_path\n",
    )
    sub(
        "hy3dpaint/utils/multiview_utils.py",
        r"^(\s*)pipeline = DiffusionPipeline\.from_pretrained\(\s*model_path,\s*custom_pipeline=custom_pipeline,\s*torch_dtype=torch\.float16\s*\)\n",
        "\\1from hunyuanpaintpbr.pipeline import HunyuanPaintPipeline\n"
        "\\1from hunyuanpaintpbr.unet.modules import UNet2p5DConditionModel\n"
        "\\1from diffusers import AutoencoderKL\n"
        "\\1from transformers import CLIPImageProcessor, CLIPTextModel, CLIPTokenizer\n"
        "\\1unet = UNet2p5DConditionModel.from_pretrained(os.path.join(model_path, \"unet\"), torch_dtype=torch.float16)\n"
        # Built from its components, each from its own local folder: model_index.json
        # names the unet library "modules", and diffusers 0.42 from_pretrained refuses a
        # passed unet that is a plain torch Module from an unimported library (live job
        # 2026-11-13). No component is resolved by a name the repository supplies.
        "\\1pipeline = HunyuanPaintPipeline(\n"
        "\\1    vae=AutoencoderKL.from_pretrained(\n"
        "\\1        os.path.join(model_path, \"vae\"), torch_dtype=torch.float16, use_safetensors=True, local_files_only=True\n"
        "\\1    ),\n"
        "\\1    text_encoder=CLIPTextModel.from_pretrained(\n"
        "\\1        os.path.join(model_path, \"text_encoder\"), dtype=torch.float16, use_safetensors=True, local_files_only=True\n"
        "\\1    ),\n"
        "\\1    tokenizer=CLIPTokenizer.from_pretrained(os.path.join(model_path, \"tokenizer\"), local_files_only=True),\n"
        "\\1    unet=unet,\n"
        "\\1    scheduler=DDIMScheduler.from_pretrained(os.path.join(model_path, \"scheduler\"), local_files_only=True),\n"
        "\\1    feature_extractor=CLIPImageProcessor.from_pretrained(\n"
        "\\1        os.path.join(model_path, \"feature_extractor\"), local_files_only=True\n"
        "\\1    ),\n"
        "\\1)\n",
    )
    sub("hy3dpaint/utils/multiview_utils.py", r"^import huggingface_hub\n", "")
    # 2. UNet weights: safetensors instead of the pickled .bin checkpoint.
    sub(
        "hy3dpaint/hunyuanpaintpbr/unet/modules.py",
        r"\"diffusion_pytorch_model\.bin\"",
        "\"diffusion_pytorch_model.safetensors\"",
    )
    sub(
        "hy3dpaint/hunyuanpaintpbr/unet/modules.py",
        r"unet_ckpt = torch\.load\(unet_ckpt_path, map_location=\"cpu\", weights_only=True\)",
        "import safetensors.torch\n        unet_ckpt = safetensors.torch.load_file(unet_ckpt_path, device=\"cpu\")",
    )
    # 3. The training wrapper (pytorch-lightning, checkpoint loading) is not
    #    part of inference; stop importing it.
    sub("hy3dpaint/hunyuanpaintpbr/__init__.py", r"^from \.unet\.model import HunyuanPaint\n", "")
    sub("hy3dpaint/hunyuanpaintpbr/__init__.py", r"^\s*'HunyuanPaint',\n", "")
    # 4. Image-model defaults point at baked local assets, never Hub ids.
    sub(
        "hy3dpaint/textureGenPipeline.py",
        r"self\.multiview_pretrained_path = \"tencent/Hunyuan3D-2\.1\"",
        "self.multiview_pretrained_path = \"/models/Hunyuan3D-2.1\"",
    )
    sub(
        "hy3dpaint/textureGenPipeline.py",
        r"self\.dino_ckpt_path = \"facebook/dinov2-giant\"",
        "self.dino_ckpt_path = \"/models/dinov2-giant\"",
    )
    sub(
        "hy3dpaint/textureGenPipeline.py",
        r"self\.realesrgan_ckpt_path = \"ckpt/RealESRGAN_x4plus\.pth\"",
        "self.realesrgan_ckpt_path = \"/models/realesrgan/RealESRGAN_x4plus.safetensors\"",
    )
    # 5. The optional external mesh simplifier shells out to a prebuilt binary;
    #    the inference path never uses it, so it is removed and disabled.
    sub(
        "hy3dshape/hy3dshape/postprocessors.py",
        r"os\.system\(f'\{self\.executable\} \{temp_input\.name\} \{temp_output\.name\}'\)",
        "raise RuntimeError('external mesh simplifier is disabled in the AIONEX runtime')",
    )
    # 5c. Remesh: trimesh's simplify_quadric_decimation needs open3d, which is not
    #     installed (live job 2026-11-13: ModuleNotFoundError). Use pymeshlab's
    #     quadric edge collapse instead; pymeshlab is already loaded by this function.
    sub(
        "hy3dpaint/utils/simplify_mesh_utils.py",
        r"^(\s*)courent = courent\.simplify_quadric_decimation\(target_count\)\n",
        "\\1ms.meshing_decimation_quadric_edge_collapse(targetfacenum=int(target_count), preservenormal=True)\n"
        "\\1ms.save_current_mesh(outputpath.replace(\".glb\", \".obj\"), save_textures=False)\n"
        "\\1courent = trimesh.load(outputpath.replace(\".glb\", \".obj\"), force=\"mesh\")\n",
    )
    # 5b. transformers 5 Dinov2 parameter names (see patch_dinov2_v5_names).
    patch_dinov2_v5_names()
    # 6. Super-resolution: reviewed safetensors-only implementation replaces the
    #    basicsr/realesrgan stack (pickle torch.load, tb-nightly, URL downloads).
    shutil.copyfile(OVERRIDES / "image_super_utils.py", ROOT / "hy3dpaint/utils/image_super_utils.py")
    for relative in REMOVE:
        target = ROOT / relative
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    # 7. Post-conditions over the remaining runtime tree.
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(ROOT).as_posix()
        if re.search(r"trust_remote_code\s*=\s*True", text):
            raise SystemExit(f"trust_remote_code enabled in {rel}")
        if re.search(r"\bos\.system\(|\bsubprocess\.", text) and "custom_rasterizer/setup.py" not in rel:
            raise SystemExit(f"shell execution remains in {rel}")
        if re.search(r"\bpickle\.loads?\(", text):
            raise SystemExit(f"pickle load remains in {rel}")
        if "snapshot_download(" in text and rel != "hy3dshape/hy3dshape/utils/utils.py":
            raise SystemExit(f"Hub download remains in {rel}")
    print("Hunyuan runtime hardening patches: PASS")


if __name__ == "__main__":
    main()
