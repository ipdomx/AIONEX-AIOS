from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import logging
import os
import json
import struct
from pathlib import Path
import time
import uuid

import numpy as np
from PIL import Image
import rembg
import runpod
import torch
import trimesh

from tsr.system import TSR
from tsr.utils import remove_background, resize_foreground
from tsr.bake_texture import bake_texture

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("aionex-triposr-worker")
MODEL_ROOT = "/models/TripoSR"
SAVE = Path("/workspace/triposr_cache")
SAVE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
os.environ.setdefault("MGL_BACKEND", "egl")
_MODEL = None
_REMBG = None


def get_model() -> TSR:
    global _MODEL
    if _MODEL is None:
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU is required")
        log.info("loading TripoSR fallback model")
        _MODEL = TSR.from_pretrained(MODEL_ROOT, config_name="config.yaml", weight_name="model.ckpt")
        _MODEL.renderer.set_chunk_size(8192)
        _MODEL.to("cuda:0")
        log.info("TripoSR fallback model loaded")
    return _MODEL


def get_rembg():
    global _REMBG
    if _REMBG is None:
        _REMBG = rembg.new_session()
    return _REMBG


def prepare_image(raw: bytes) -> Image.Image:
    image = Image.open(BytesIO(raw)).convert("RGBA")
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
    resolution = max(128, min(int(payload.get("mc_resolution", 192)), 256))
    texture_resolution = max(512, min(int(payload.get("texture_size", 1024)), 2048))
    try:
        source = base64.b64decode(raw, validate=True)
        image = prepare_image(source)
        model = get_model()
        with torch.no_grad():
            scene_codes = model([image], device="cuda:0")
            mesh = model.extract_mesh(scene_codes, False, resolution=resolution)[0]
        work = SAVE / str(uuid.uuid4())
        work.mkdir(parents=True, exist_ok=True)
        final, inspection = _textured_glb(model, scene_codes, mesh, work, texture_resolution)
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


if __name__ == "__main__":
    log.info("starting AIONEX TripoSR MIT fallback worker")
    runpod.serverless.start({"handler": handler})
