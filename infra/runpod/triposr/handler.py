"""AIONEX TripoSR MIT fallback RunPod handler (FR-16D hardening applied).

Model assets are baked, checksum-verified safetensors; torch.load and Hub
downloads are disabled in-process; requests are validated (size, type, pixel
count, scalar ranges) before model work; outputs are size-limited.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import logging
import os
import json
import shutil
import struct
from pathlib import Path
import time
import uuid

for _name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
    os.environ[_name] = "1"

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import rembg  # noqa: E402
import runpod  # noqa: E402
import safetensors.torch  # noqa: E402
import torch  # noqa: E402
import trimesh  # noqa: E402
from omegaconf import OmegaConf  # noqa: E402

from input_guard import InputError, bounded_int, decode_image, reject_unknown_fields  # noqa: E402
from tsr.system import TSR  # noqa: E402
from tsr.utils import remove_background, resize_foreground  # noqa: E402
from tsr.bake_texture import bake_texture  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aionex-triposr-worker")
MODEL_ROOT = "/models/TripoSR"
SAVE = Path(os.environ.get("AIONEX_TRIPOSR_WORKDIR", "/tmp/aionex-triposr"))
MAX_OUTPUT_BYTES = int(os.environ.get("AIONEX_TRIPOSR_MAX_OUTPUT_BYTES", str(100 * 1024 * 1024)))
INPUT_KEYS = frozenset({"image", "mc_resolution", "texture_size"})
os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
os.environ.setdefault("MGL_BACKEND", "egl")
_MODEL = None
_REMBG = None


# The TripoSR checkpoint was saved with transformers 4.x ViT parameter names;
# transformers 5 renamed the ViT encoder blocks. Map the old names onto the new
# ones so the pinned checkpoint loads strictly (no missing/unexpected keys).
_VIT_PREFIX = "image_tokenizer.model."
_VIT_V5_RENAMES = (
    (".attention.attention.query.", ".attention.q_proj."),
    (".attention.attention.key.", ".attention.k_proj."),
    (".attention.attention.value.", ".attention.v_proj."),
    (".attention.output.dense.", ".attention.o_proj."),
    (".intermediate.dense.", ".mlp.fc1."),
    (".output.dense.", ".mlp.fc2."),
)


def remap_checkpoint_keys(state: dict, expected_keys) -> dict:
    expected = set(expected_keys)
    old_block = _VIT_PREFIX + "encoder.layer."
    if not any(key.startswith(old_block) for key in state) or any(key.startswith(old_block) for key in expected):
        return state
    remapped = {}
    for key, value in state.items():
        if key.startswith(old_block):
            new_key = _VIT_PREFIX + "layers." + key[len(old_block):]
            for old, new in _VIT_V5_RENAMES:
                if old in new_key:
                    new_key = new_key.replace(old, new, 1)
                    break
            key = new_key
        remapped[key] = value
    return remapped


def build_model() -> TSR:
    # Equivalent to TSR.from_pretrained, but loads the build-time
    # safetensors conversion instead of the pickled model.ckpt.
    cfg = OmegaConf.load(os.path.join(MODEL_ROOT, "config.yaml"))
    OmegaConf.resolve(cfg)
    model = TSR(cfg)
    state = safetensors.torch.load_file(os.path.join(MODEL_ROOT, "model.safetensors"), device="cpu")
    model.load_state_dict(remap_checkpoint_keys(state, model.state_dict().keys()), strict=True)
    return model


def get_model() -> TSR:
    global _MODEL
    if _MODEL is None:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU is required")
        log.info("loading TripoSR fallback model")
        _MODEL = build_model()
        _MODEL.renderer.set_chunk_size(8192)
        _MODEL.to("cuda:0")
        log.info("TripoSR fallback model loaded")
    return _MODEL


def get_rembg():
    global _REMBG
    if _REMBG is None:
        # rembg 2.0.87 changed the default to "bria-rmbg", which is not baked and
        # would be downloaded at runtime. Only the build-time u2net.onnx is allowed.
        _REMBG = rembg.new_session("u2net")
    return _REMBG


def _forbidden(name: str):
    def _raise(*_args: object, **_kwargs: object):
        raise RuntimeError(f"{name} is disabled in the AIONEX TripoSR runtime")

    return _raise


def install_runtime_guards() -> None:
    torch.load = _forbidden("torch.load (pickle)")  # type: ignore[assignment]
    torch.hub.load = _forbidden("torch.hub.load")  # type: ignore[assignment]
    import huggingface_hub

    for helper in ("snapshot_download", "hf_hub_download"):
        if hasattr(huggingface_hub, helper):
            setattr(huggingface_hub, helper, _forbidden(f"huggingface_hub.{helper}"))
    import tsr.system
    import tsr.models.tokenizers.image as image_tokenizer

    tsr.system.hf_hub_download = _forbidden("huggingface_hub.hf_hub_download")
    image_tokenizer.hf_hub_download = _forbidden("huggingface_hub.hf_hub_download")


def prepare_image(image: Image.Image) -> Image.Image:
    image = remove_background(image, get_rembg())
    image = resize_foreground(image, 0.85)
    array = np.array(image).astype(np.float32) / 255.0
    array = array[:, :, :3] * array[:, :, 3:4] + (1 - array[:, :, 3:4]) * 0.5
    return Image.fromarray((array * 255.0).astype(np.uint8))


def _inspect_glb(path: Path) -> dict[str, int]:
    body = path.read_bytes()
    if len(body) < 20 or body[:4] != b"glTF":
        raise RuntimeError("fallback artifact is not GLB")
    version, total_length = struct.unpack_from("<II", body, 4)
    if version != 2 or total_length != len(body):
        raise RuntimeError("fallback GLB header is invalid")
    json_length, json_type = struct.unpack_from("<II", body, 12)
    if json_type != 0x4E4F534A or 20 + json_length > len(body):
        raise RuntimeError("fallback GLB JSON chunk is invalid")
    document = json.loads(body[20 : 20 + json_length].decode("utf-8").rstrip(" \x00"))
    meshes = list(document.get("meshes") or [])
    materials = list(document.get("materials") or [])
    images = list(document.get("images") or [])
    pbr = sum(1 for item in materials if isinstance(item, dict) and item.get("pbrMetallicRoughness"))
    if not meshes or not materials or not images or pbr < 1:
        raise RuntimeError("fallback GLB is missing mesh/PBR/texture data")
    return {
        "mesh_count": len(meshes),
        "material_count": len(materials),
        "pbr_material_count": pbr,
        "texture_count": len(images),
    }


def _textured_glb(model: TSR, scene_codes, mesh: trimesh.Trimesh, work: Path, texture_resolution: int) -> tuple[Path, dict[str, int]]:
    baked = bake_texture(mesh, model, scene_codes[0], texture_resolution)
    vertices = mesh.vertices[baked["vmapping"]]
    normals = mesh.vertex_normals[baked["vmapping"]]
    texture = Image.fromarray((baked["colors"] * 255.0).astype(np.uint8)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=texture, metallicFactor=0.0, roughnessFactor=0.9
    )
    visual = trimesh.visual.texture.TextureVisuals(uv=baked["uvs"], material=material)
    textured = trimesh.Trimesh(
        vertices=vertices, faces=baked["indices"], vertex_normals=normals, visual=visual, process=False
    )
    textured.remove_unreferenced_vertices()
    final = work / "final.glb"
    final.write_bytes(trimesh.exchange.gltf.export_glb(textured))
    inspection = _inspect_glb(final)
    # Independent round-trip guards against a structurally valid but unloadable file.
    loaded = trimesh.load(final, force="scene")
    if not getattr(loaded, "geometry", None):
        raise RuntimeError("fallback GLB round-trip validation failed")
    return final, inspection


def handler(job: dict) -> dict:
    started = time.monotonic()
    payload = job.get("input") or {}
    if not isinstance(payload, dict):
        return {"error": "input must be an object"}
    raw = payload.get("image")
    if not isinstance(raw, str) or not raw:
        return {"error": "input.image required"}
    try:
        reject_unknown_fields(payload, INPUT_KEYS)
        resolution = max(128, min(bounded_int(payload, "mc_resolution", 192, 1, 4096), 256))
        texture_resolution = max(512, min(bounded_int(payload, "texture_size", 1024, 1, 1 << 16), 2048))
        source_image = decode_image(raw)
    except InputError as exc:
        return {"error": str(exc)}
    work = SAVE / str(uuid.uuid4())
    try:
        image = prepare_image(source_image)
        model = get_model()
        with torch.no_grad():
            scene_codes = model([image], device="cuda:0")
            mesh = model.extract_mesh(scene_codes, False, resolution=resolution)[0]
        work.mkdir(mode=0o700, parents=True, exist_ok=False)
        final, inspection = _textured_glb(model, scene_codes, mesh, work, texture_resolution)
        if final.stat().st_size > MAX_OUTPUT_BYTES:
            raise RuntimeError("fallback artifact exceeds the output size limit")
        body = final.read_bytes()
        if body[:4] != b"glTF":
            raise RuntimeError("fallback artifact is not GLB")
        digest = sha256(body).hexdigest()
        elapsed = round(time.monotonic() - started, 3)
        manifest = {
            "pipeline": "triposr-mit-textured-fallback",
            "model_revision": "5b521936b01fbe1890f6f9baed0254ab6351c04a",
            "source_revision": "107cefdc244c39106fa830359024f6a2f1c78871",
            "license": "MIT",
            **inspection,
            "texture_size_limit": texture_resolution,
            "compression_policy": "compat",
            "fallback_used": True,
            "fallback_provider": "triposr",
            "sha256": digest,
            "timings": {"total_seconds": elapsed},
        }
        return {
            "filename": "final.glb",
            "content_type": "model/gltf-binary",
            "size_bytes": len(body),
            "sha256": digest,
            "manifest": manifest,
            "content_base64": base64.b64encode(body).decode("ascii"),
        }
    except Exception as exc:
        log.exception("TripoSR fallback handler failed")
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    install_runtime_guards()
    SAVE.mkdir(mode=0o700, parents=True, exist_ok=True)
    log.info("starting AIONEX TripoSR MIT fallback worker")
    runpod.serverless.start({"handler": handler})
