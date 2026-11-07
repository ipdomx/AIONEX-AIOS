"""Headless Blender conversion script for the AIONEX three-d-worker.

This file runs *inside* Blender's bundled Python (``blender --background
--factory-startup --disable-autoexec --offline-mode --python-exit-code 1
--python three_d_convert.py -- <spec.json>``). It never imports the AIOS
application, never reads user preferences or add-ons outside the factory set,
and refuses network access before any importer runs.

The spec is written by ``app.services.three_d_conversion`` into a private temp
directory. Every path in it is inside that directory; the script re-checks this
before reading or writing.
"""
from __future__ import annotations

import json
import math
import os
import socket
import sys
from pathlib import Path


def _deny_network(*_args: object, **_kwargs: object) -> None:
    raise OSError("network access is disabled inside the AIONEX Blender sandbox")


# Refuse sockets before bpy or any importer/add-on code can open one. Blender's
# --offline-mode already disables online add-on access; this is the in-process
# backstop. Kernel-level isolation is documented as residual risk in FR-16D.
socket.socket = _deny_network  # type: ignore[assignment,misc]
socket.create_connection = _deny_network  # type: ignore[assignment]
socket.getaddrinfo = _deny_network  # type: ignore[assignment]

import bpy  # noqa: E402  (must follow the network guard)

IMPORTERS = {
    "glb": lambda path: bpy.ops.import_scene.gltf(filepath=path),
    "obj": lambda path: bpy.ops.wm.obj_import(filepath=path),
    "fbx": lambda path: bpy.ops.import_scene.fbx(filepath=path),
    "usdz": lambda path: bpy.ops.wm.usd_import(filepath=path),
}


def _export(fmt: str, path: str) -> None:
    if fmt == "glb":
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True)
    elif fmt == "obj":
        bpy.ops.wm.obj_export(filepath=path, export_materials=True, path_mode="COPY")
    elif fmt == "fbx":
        bpy.ops.export_scene.fbx(filepath=path, path_mode="COPY", embed_textures=True)
    elif fmt == "usdz":
        bpy.ops.wm.usd_export(filepath=path)
    else:
        raise ValueError(f"unsupported export format: {fmt}")


def _inside(root: Path, value: str) -> str:
    candidate = Path(value).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("conversion path escapes the sandbox directory")
    return str(candidate)


def _frame_camera(size: int) -> None:
    from mathutils import Vector

    scene = bpy.context.scene
    meshes = [obj for obj in scene.objects if obj.type == "MESH"]
    if not meshes:
        raise ValueError("model has no mesh to preview")
    points = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = Vector([min(p[i] for p in points) for i in range(3)])
    high = Vector([max(p[i] for p in points) for i in range(3)])
    center = (low + high) / 2
    radius = max(1e-6, max(high - low)) * 0.9
    camera_data = bpy.data.cameras.new("aionex-preview")
    camera_data.lens = 50
    camera = bpy.data.objects.new("aionex-preview", camera_data)
    scene.collection.objects.link(camera)
    distance = radius / math.tan(camera_data.angle / 2) + radius
    camera.location = center + Vector((0.7, -0.7, 0.5)).normalized() * distance
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = camera
    light_data = bpy.data.lights.new("aionex-key", type="SUN")
    light_data.energy = 3.0
    light = bpy.data.objects.new("aionex-key", light_data)
    light.rotation_euler = (0.8, 0.2, 0.6)
    scene.collection.objects.link(light)
    world = bpy.data.worlds.new("aionex-preview")
    world.color = (0.18, 0.18, 0.2)
    scene.world = world
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 16
    scene.cycles.use_denoising = False
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"


def main() -> int:
    spec_path = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    root = spec_path.parent
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    source_format = str(spec["input_format"])
    if source_format not in IMPORTERS:
        raise ValueError(f"unsupported input format: {source_format}")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    IMPORTERS[source_format](_inside(root, spec["input"]))
    results: dict[str, dict[str, object]] = {}
    for item in spec.get("outputs") or []:
        fmt = str(item["format"])
        target = _inside(root, item["path"])
        Path(target).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            _export(fmt, target)
            results[fmt] = {"ok": Path(target).is_file()}
        except Exception as exc:  # each format degrades independently
            results[fmt] = {"ok": False, "error": type(exc).__name__}
    thumbnail = spec.get("thumbnail")
    if thumbnail:
        target = _inside(root, thumbnail["path"])
        try:
            _frame_camera(int(thumbnail["size"]))
            bpy.context.scene.render.filepath = target
            bpy.ops.render.render(write_still=True)
            results["thumbnail"] = {"ok": Path(target).is_file()}
        except Exception as exc:
            results["thumbnail"] = {"ok": False, "error": type(exc).__name__}
    result_path = Path(_inside(root, spec["result"]))
    result_path.write_text(json.dumps({"blender": bpy.app.version_string, "results": results}), encoding="utf-8")
    os.chmod(result_path, 0o600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
