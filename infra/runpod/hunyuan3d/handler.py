from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import types
import uuid

import numpy as np
from PIL import Image
import runpod
import torch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aionex-hunyuan3d-worker")

ROOT = Path("/opt/Hunyuan3D-2.1")
MODEL_ROOT = Path("/models/Hunyuan3D-2.1")
DINO_ROOT = Path("/models/dinov2-giant")
SAVE = Path("/workspace/gradio_cache")
BLENDER_SCRIPT = Path("/opt/phase34c_blender.py")
SAVE.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "hy3dshape"))
sys.path.insert(0, str(ROOT / "hy3dpaint"))
os.chdir(ROOT)

_SHAPE_PIPE = None
_PAINT_PIPE = None


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def get_shape_pipe():
    global _SHAPE_PIPE
    if _SHAPE_PIPE is None:
        log.info("loading Hunyuan3D shape pipeline from %s", MODEL_ROOT)
        from hy3dshape import Hunyuan3DDiTFlowMatchingPipeline

        _SHAPE_PIPE = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            str(MODEL_ROOT), subfolder="hunyuan3d-dit-v2-1"
        )
        log.info("Hunyuan3D shape pipeline loaded")
    return _SHAPE_PIPE


def get_paint_pipe():
    global _PAINT_PIPE
    if _PAINT_PIPE is None:
        # textureGenPipeline imports mesh_utils, which imports bpy even when its
        # OBJ->GLB converter is not used. Keep the real mesh_utils module so
        # load_mesh/save_mesh remain available, but provide a minimal bpy module
        # during import. Blender conversion is executed later in a separate CLI.
        if "bpy" not in sys.modules:
            sys.modules["bpy"] = types.ModuleType("bpy")
        from torchvision_fix import apply_fix
        apply_fix()
        from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

        conf = Hunyuan3DPaintConfig(6, 512)
        conf.realesrgan_ckpt_path = str(ROOT / "hy3dpaint" / "ckpt" / "RealESRGAN_x4plus.pth")
        conf.multiview_cfg_path = "hy3dpaint/cfgs/hunyuan-paint-pbr.yaml"
        conf.custom_pipeline = "hy3dpaint/hunyuanpaintpbr"
        conf.multiview_pretrained_path = str(MODEL_ROOT)
        conf.dino_ckpt_path = str(DINO_ROOT)
        log.info("loading Hunyuan3D PBR paint pipeline")
        _PAINT_PIPE = Hunyuan3DPaintPipeline(conf)
        log.info("Hunyuan3D PBR paint pipeline loaded")
    return _PAINT_PIPE


def _run(command: list[str], *, timeout: int) -> None:
    result = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        tail = (result.stdout or "")[-4000:]
        raise RuntimeError(f"command failed ({command[0]}): {tail}")


def _pbr_glb(obj_path: Path, output_path: Path) -> dict[str, object]:
    from hy3dpaint.convert_utils import create_glb_with_pbr_materials

    textures = {
        "albedo": str(obj_path.with_suffix(".jpg")),
        "metallic": str(obj_path.with_name(obj_path.stem + "_metallic.jpg")),
        "roughness": str(obj_path.with_name(obj_path.stem + "_roughness.jpg")),
    }
    missing = [name for name, value in textures.items() if not Path(value).is_file()]
    if missing:
        raise RuntimeError("missing generated PBR textures: " + ", ".join(missing))
    create_glb_with_pbr_materials(str(obj_path), textures, str(output_path))
    return {name: Path(value).stat().st_size for name, value in textures.items()}


def _inspect_glb(path: Path) -> dict[str, int]:
    from pygltflib import GLTF2

    gltf = GLTF2().load(str(path))
    materials = list(gltf.materials or [])
    images = list(gltf.images or [])
    meshes = list(gltf.meshes or [])
    if not materials or not images or not meshes:
        raise RuntimeError("optimized GLB is missing mesh/material/texture data")
    pbr = sum(1 for material in materials if material.pbrMetallicRoughness is not None)
    if pbr < 1:
        raise RuntimeError("optimized GLB has no PBR metallic-roughness material")
    return {
        "mesh_count": len(meshes),
        "material_count": len(materials),
        "pbr_material_count": pbr,
        "texture_count": len(images),
    }


def _post_process(source: Path, output: Path, policy: str, texture_size: int) -> tuple[dict[str, object], dict[str, float]]:
    timings: dict[str, float] = {}
    blender_out = source.with_name(source.stem + "_blender.glb")
    started = time.monotonic()
    _run(["blender", "--background", "--python", str(BLENDER_SCRIPT), "--", str(source), str(blender_out)], timeout=900)
    timings["blender_seconds"] = round(time.monotonic() - started, 3)

    if policy not in {"compat", "meshopt"}:
        raise ValueError("compression_policy must be compat or meshopt")
    compress = "false" if policy == "compat" else "meshopt"
    texture_format = "auto" if policy == "compat" else "webp"
    started = time.monotonic()
    _run(
        [
            "gltf-transform", "optimize", str(blender_out), str(output),
            "--compress", compress,
            "--texture-compress", texture_format,
            "--texture-size", str(texture_size),
            "--simplify", "false",
            "--flatten", "true",
            "--join", "true",
            "--weld", "true",
            "--prune", "true",
        ],
        timeout=900,
    )
    _run(["gltf-transform", "inspect", str(output)], timeout=300)
    timings["gltf_transform_seconds"] = round(time.monotonic() - started, 3)
    return _inspect_glb(output), timings


def handler(job: dict) -> dict:
    started = time.monotonic()
    payload = job.get("input") or {}
    if not isinstance(payload, dict):
        return {"error": "input must be an object"}
    raw = payload.get("image")
    if not raw:
        return {"error": "input.image required"}
    allow_fallback = bool(payload.get("allow_shape_fallback", False))
    seed = int(payload.get("seed", 12345))
    texture_size = max(512, min(int(payload.get("texture_size", 2048)), 4096))
    compression_policy = str(payload.get("compression_policy", "compat"))
    uid = uuid.uuid4()
    work = SAVE / str(uid)
    work.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    fallback_reason: str | None = None
    _seed_everything(seed)

    try:
        image = Image.open(BytesIO(base64.b64decode(raw))).convert("RGBA")
        input_path = work / "input.png"
        image.save(input_path)

        mark = time.monotonic()
        mesh = get_shape_pipe()(image=image, generator=torch.Generator(device="cuda").manual_seed(seed))[0]
        shape_path = work / "shape.glb"
        mesh.export(shape_path)
        timings["shape_seconds"] = round(time.monotonic() - mark, 3)

        final_path: Path
        metadata: dict[str, object]
        try:
            mark = time.monotonic()
            textured_obj = work / "textured.obj"
            get_paint_pipe()(mesh_path=str(shape_path), image_path=image, output_mesh_path=str(textured_obj), save_glb=False)
            timings["texture_seconds"] = round(time.monotonic() - mark, 3)
            pbr_source = work / "pbr_source.glb"
            texture_bytes = _pbr_glb(textured_obj, pbr_source)
            pre_size = pbr_source.stat().st_size
            final_path = work / "final.glb"
            inspection, post_timings = _post_process(pbr_source, final_path, compression_policy, texture_size)
            timings.update(post_timings)
            metadata = {
                **inspection,
                "texture_bytes": texture_bytes,
                "pre_optimization_bytes": pre_size,
                "post_optimization_bytes": final_path.stat().st_size,
                "optimization_ratio": round(final_path.stat().st_size / max(1, pre_size), 6),
                "compression_policy": compression_policy,
                "texture_size_limit": texture_size,
                "fallback_used": False,
            }
        except Exception as exc:
            if not allow_fallback:
                raise
            fallback_reason = f"{type(exc).__name__}: {exc}"
            log.exception("PBR path failed; explicit shape-only fallback permitted")
            final_path = work / "final_shape_fallback.glb"
            shape_path.replace(final_path)
            metadata = {
                "mesh_count": 1,
                "material_count": 0,
                "pbr_material_count": 0,
                "texture_count": 0,
                "pre_optimization_bytes": final_path.stat().st_size,
                "post_optimization_bytes": final_path.stat().st_size,
                "optimization_ratio": 1.0,
                "compression_policy": "none",
                "texture_size_limit": texture_size,
                "fallback_used": True,
                "fallback_reason": fallback_reason,
            }

        body = final_path.read_bytes()
        if body[:4] != b"glTF":
            raise RuntimeError("final artifact is not GLB")
        digest = sha256(body).hexdigest()
        timings["total_seconds"] = round(time.monotonic() - started, 3)
        manifest = {
            "pipeline": "hunyuan3d-2.1-pbr-phase34c",
            "seed": seed,
            "sha256": digest,
            **metadata,
            "timings": timings,
        }
        log.info("generated final GLB bytes=%s sha256=%s fallback=%s", len(body), digest, metadata["fallback_used"])
        return {
            "filename": final_path.name,
            "content_type": "model/gltf-binary",
            "size_bytes": len(body),
            "sha256": digest,
            "manifest": manifest,
            "content_base64": base64.b64encode(body).decode("ascii"),
        }
    except Exception as exc:
        log.exception("Phase 34C handler failed")
        return {"error": f"{type(exc).__name__}: {exc}", "fallback_allowed": allow_fallback}

if __name__ == "__main__":
    log.info(
        "starting RunPod serverless handler sdk=%s python=%s",
        getattr(runpod, "__version__", "unknown"),
        sys.version.split()[0],
    )
    runpod.serverless.start({"handler": handler})
