"""AIONEX Hunyuan3D 2.1 PBR RunPod serverless handler (FR-16D hardened).

Security posture (see docs/project/receipts/FR16D-hunyuan-security-review-20261107.md):

* Model assets are baked at build time from a pinned Hugging Face revision,
  verified against SHA-256 checksums and converted to safetensors. No pickle
  file exists in the runtime image and ``torch.load`` is disabled in-process.
* Hugging Face / torch.hub downloads are disabled at runtime: offline env vars
  plus in-process guards that raise if any download helper is called. Only the
  RunPod SDK talks to the network.
* Hunyuan Python code is the reviewed upstream commit, patched at build time;
  Diffusers' ``custom_pipeline`` is confined to that vendored directory and
  ``trust_remote_code`` is never enabled.
* Requests are validated before any model work: payload size, image type,
  pixel count (decompression-bomb guard) and every scalar option. Outputs are
  size-limited, every subprocess has a timeout, and the job has a deadline.
"""
from __future__ import annotations

import base64
from hashlib import sha256
import logging
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import types
import uuid

for _name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE", "DIFFUSERS_OFFLINE"):
    os.environ[_name] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

import numpy as np  # noqa: E402
import runpod  # noqa: E402
import torch  # noqa: E402

from input_guard import SEED_MAX, InputError, bounded_int, decode_image, reject_unknown_fields  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aionex-hunyuan3d-worker")

ROOT = Path("/opt/Hunyuan3D-2.1")
MODEL_ROOT = Path("/models/Hunyuan3D-2.1")
DINO_ROOT = Path("/models/dinov2-giant")
REALESRGAN_WEIGHTS = Path("/models/realesrgan/RealESRGAN_x4plus.safetensors")
SAVE = Path(os.environ.get("AIONEX_HUNYUAN_WORKDIR", "/tmp/aionex-hunyuan"))
BLENDER = "/opt/blender/blender"
BLENDER_SCRIPT = Path("/opt/phase34c_blender.py")
GLTF_TRANSFORM = "/opt/gltf-tools/node_modules/.bin/gltf-transform"

MAX_OUTPUT_BYTES = int(os.environ.get("AIONEX_HUNYUAN_MAX_OUTPUT_BYTES", str(100 * 1024 * 1024)))
JOB_DEADLINE_SECONDS = int(os.environ.get("AIONEX_HUNYUAN_DEADLINE_SECONDS", "3000"))
INPUT_KEYS = frozenset({"image", "seed", "texture_size", "compression_policy", "allow_shape_fallback"})

_SHAPE_PIPE = None
_PAINT_PIPE = None


def _forbidden(name: str):
    def _raise(*_args: object, **_kwargs: object):
        raise RuntimeError(f"{name} is disabled in the AIONEX Hunyuan runtime")

    return _raise


def install_runtime_guards() -> None:
    """Fail closed on pickle loads and runtime model/code downloads."""
    torch.load = _forbidden("torch.load (pickle)")  # type: ignore[assignment]
    torch.hub.load = _forbidden("torch.hub.load")  # type: ignore[assignment]
    torch.hub.download_url_to_file = _forbidden("torch.hub.download_url_to_file")  # type: ignore[assignment]
    import huggingface_hub

    for helper in ("snapshot_download", "hf_hub_download", "hf_hub_url"):
        if hasattr(huggingface_hub, helper):
            setattr(huggingface_hub, helper, _forbidden(f"huggingface_hub.{helper}"))
    import huggingface_hub.file_download as file_download

    file_download.hf_hub_download = _forbidden("huggingface_hub.hf_hub_download")  # type: ignore[assignment]


def _prepare_import_path() -> None:
    for entry in (ROOT / "hy3dpaint", ROOT / "hy3dshape", ROOT):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    os.chdir(ROOT)


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
            str(MODEL_ROOT), subfolder="hunyuan3d-dit-v2-1", use_safetensors=True
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
        from textureGenPipeline import Hunyuan3DPaintConfig, Hunyuan3DPaintPipeline

        conf = Hunyuan3DPaintConfig(6, 512)
        conf.realesrgan_ckpt_path = str(REALESRGAN_WEIGHTS)
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
        env={"PATH": "/opt/node/bin:/usr/bin:/bin", "HOME": str(SAVE), "NO_COLOR": "1"},
    )
    if result.returncode:
        tail = (result.stdout or "")[-4000:]
        raise RuntimeError(f"command failed ({Path(command[0]).name}): {tail}")


def parse_options(payload: dict) -> dict[str, object]:
    reject_unknown_fields(payload, INPUT_KEYS)
    allow_fallback = payload.get("allow_shape_fallback", False)
    if not isinstance(allow_fallback, bool):
        raise InputError("allow_shape_fallback must be a boolean")
    seed = bounded_int(payload, "seed", 12345, 0, SEED_MAX)
    texture_size = bounded_int(payload, "texture_size", 2048, 1, 1 << 16)
    compression_policy = payload.get("compression_policy", "compat")
    if compression_policy not in {"compat", "meshopt"}:
        raise InputError("compression_policy must be compat or meshopt")
    return {
        "allow_fallback": allow_fallback,
        "seed": seed,
        "texture_size": max(512, min(texture_size, 4096)),
        "compression_policy": compression_policy,
    }


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
    _run(
        [
            BLENDER, "--background", "--factory-startup", "--disable-autoexec", "--offline-mode",
            "--python-exit-code", "1", "--python", str(BLENDER_SCRIPT), "--", str(source), str(blender_out),
        ],
        timeout=900,
    )
    timings["blender_seconds"] = round(time.monotonic() - started, 3)

    if policy not in {"compat", "meshopt"}:
        raise ValueError("compression_policy must be compat or meshopt")
    compress = "false" if policy == "compat" else "meshopt"
    texture_format = "auto" if policy == "compat" else "webp"
    started = time.monotonic()
    _run(
        [
            GLTF_TRANSFORM, "optimize", str(blender_out), str(output),
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
    _run([GLTF_TRANSFORM, "inspect", str(output)], timeout=300)
    timings["gltf_transform_seconds"] = round(time.monotonic() - started, 3)
    return _inspect_glb(output), timings


def _check_deadline(started: float) -> None:
    if time.monotonic() - started > JOB_DEADLINE_SECONDS:
        raise TimeoutError("Hunyuan job exceeded its deadline")


def handler(job: dict) -> dict:
    started = time.monotonic()
    payload = job.get("input") or {}
    if not isinstance(payload, dict):
        return {"error": "input must be an object"}
    if not payload.get("image"):
        return {"error": "input.image required"}
    try:
        options = parse_options(payload)
        image = decode_image(payload.get("image"))
    except InputError as exc:
        return {"error": str(exc)}
    allow_fallback = bool(options["allow_fallback"])
    seed = int(options["seed"])  # type: ignore[arg-type]
    texture_size = int(options["texture_size"])  # type: ignore[arg-type]
    compression_policy = str(options["compression_policy"])
    work = SAVE / str(uuid.uuid4())
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    timings: dict[str, float] = {}
    fallback_reason: str | None = None
    _seed_everything(seed)

    try:
        input_path = work / "input.png"
        image.save(input_path)

        mark = time.monotonic()
        mesh = get_shape_pipe()(image=image, generator=torch.Generator(device="cuda").manual_seed(seed))[0]
        shape_path = work / "shape.glb"
        mesh.export(shape_path)
        timings["shape_seconds"] = round(time.monotonic() - mark, 3)
        _check_deadline(started)

        final_path: Path
        metadata: dict[str, object]
        try:
            mark = time.monotonic()
            textured_obj = work / "textured.obj"
            get_paint_pipe()(mesh_path=str(shape_path), image_path=image, output_mesh_path=str(textured_obj), save_glb=False)
            timings["texture_seconds"] = round(time.monotonic() - mark, 3)
            _check_deadline(started)
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

        if final_path.stat().st_size > MAX_OUTPUT_BYTES:
            raise RuntimeError("final artifact exceeds the output size limit")
        body = final_path.read_bytes()
        if body[:4] != b"glTF":
            raise RuntimeError("final artifact is not GLB")
        digest = sha256(body).hexdigest()
        timings["total_seconds"] = round(time.monotonic() - started, 3)
        manifest = {
            "pipeline": "hunyuan3d-2.1-pbr-phase34c",
            "image_contract": "fr16d-hardened",
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
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    install_runtime_guards()
    _prepare_import_path()
    SAVE.mkdir(mode=0o700, parents=True, exist_ok=True)
    log.info(
        "starting RunPod serverless handler sdk=%s python=%s",
        getattr(runpod, "__version__", "unknown"),
        sys.version.split()[0],
    )
    runpod.serverless.start({"handler": handler})
