"""Governed Blender 5.2 LTS candidate for Phase 36I 3D expansion.

The runner is intentionally local-only: it uses Blender offline/background mode,
accepts only a verified 5.2.x executable, writes below a bounded workspace, and
never replaces the host renderer or submits work to an external provider.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from .expansion import BLENDER_PRODUCTION_BASELINE, probe_blender

_SAFE_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\Z")


class BlenderCandidateError(RuntimeError):
    """The isolated Blender candidate cannot execute safely."""


@dataclass(frozen=True, slots=True)
class PBRMaterialPlan:
    name: str = "aionex-material"
    base_color: tuple[float, float, float, float] = (0.08, 0.42, 0.82, 1.0)
    metallic: float = 0.35
    roughness: float = 0.28
    texture_size: int = 4

    def validate(self) -> None:
        if not _SAFE_ID.fullmatch(self.name):
            raise BlenderCandidateError("material name is invalid")
        if len(self.base_color) != 4 or any(not 0.0 <= value <= 1.0 for value in self.base_color):
            raise BlenderCandidateError("base color channels must be between zero and one")
        if not 0.0 <= self.metallic <= 1.0 or not 0.0 <= self.roughness <= 1.0:
            raise BlenderCandidateError("PBR metallic and roughness must be between zero and one")
        if self.texture_size not in {2, 4, 8, 16}:
            raise BlenderCandidateError("candidate texture size is outside the deterministic set")


@dataclass(frozen=True, slots=True)
class AnimationPlan:
    frame_start: int = 1
    frame_end: int = 48
    travel_x: float = 2.5

    def validate(self) -> None:
        if self.frame_start < 1 or self.frame_end <= self.frame_start or self.frame_end > 600:
            raise BlenderCandidateError("animation frame range is invalid")
        if not 0.1 <= abs(self.travel_x) <= 20.0:
            raise BlenderCandidateError("animation travel is outside the bounded range")


@dataclass(frozen=True, slots=True)
class EnvironmentPlan:
    ground_size: float = 8.0
    world_strength: float = 0.35
    key_light_energy: float = 900.0

    def validate(self) -> None:
        if not 2.0 <= self.ground_size <= 50.0:
            raise BlenderCandidateError("environment ground size is outside the bounded range")
        if not 0.0 <= self.world_strength <= 2.0:
            raise BlenderCandidateError("environment world strength is outside the bounded range")
        if not 10.0 <= self.key_light_energy <= 5000.0:
            raise BlenderCandidateError("environment light energy is outside the bounded range")


@dataclass(frozen=True, slots=True)
class BlenderScenePlan:
    project_id: str
    material: PBRMaterialPlan = PBRMaterialPlan()
    animation: AnimationPlan = AnimationPlan()
    environment: EnvironmentPlan = EnvironmentPlan()

    def validate(self) -> None:
        if not _SAFE_ID.fullmatch(self.project_id):
            raise BlenderCandidateError("project id is invalid")
        self.material.validate()
        self.animation.validate()
        self.environment.validate()


@dataclass(frozen=True, slots=True)
class BlenderArtifact:
    project_id: str
    blender_version: str
    glb_path: str
    preview_path: str
    glb_sha256: str
    preview_sha256: str
    glb_bytes: int
    preview_bytes: int
    network_used: bool = False
    provider_used: bool = False
    gpu_job_used: bool = False

    def snapshot(self) -> dict[str, object]:
        return asdict(self)


class Blender52CandidateRunner:
    """Execute a deterministic material/animation/environment scene offline."""

    def __init__(self, *, executable: str | Path, workspace_root: str | Path) -> None:
        self.executable = Path(executable).resolve()
        self.workspace_root = Path(workspace_root).resolve()

    def preflight(self) -> dict[str, object]:
        probe = probe_blender(str(self.executable))
        if not probe.production_approved or not probe.version.startswith("5.2."):
            raise BlenderCandidateError(
                f"Blender candidate must satisfy {BLENDER_PRODUCTION_BASELINE} LTS and remain on 5.2.x"
            )
        return probe.snapshot()

    def render(self, plan: BlenderScenePlan, destination: str | Path, *, timeout_seconds: int = 120) -> BlenderArtifact:
        plan.validate()
        if timeout_seconds < 10 or timeout_seconds > 300:
            raise BlenderCandidateError("renderer timeout must be between 10 and 300 seconds")
        root = self.workspace_root
        root.mkdir(parents=True, exist_ok=True)
        dest = Path(destination)
        if not dest.is_absolute():
            dest = root / dest
        dest = dest.resolve()
        if dest != root and root not in dest.parents:
            raise BlenderCandidateError("renderer destination escapes the bounded workspace")
        dest.mkdir(parents=True, exist_ok=True)
        self.preflight()

        script = dest / "build_scene.py"
        glb = dest / "scene.glb"
        preview = dest / "preview.png"
        manifest = dest / "renderer-manifest.json"
        script.write_text(self._script(plan, glb, preview), encoding="utf-8")
        script.chmod(0o600)

        env = {key: os.environ[key] for key in ("LANG", "LC_ALL", "TZ") if key in os.environ}
        env.update({"HOME": str(dest / ".home"), "NO_COLOR": "1"})
        Path(env["HOME"]).mkdir(mode=0o700, exist_ok=True)
        command = [
            str(self.executable),
            "--background",
            "--factory-startup",
            "--disable-autoexec",
            "--offline-mode",
            "--python",
            str(script),
        ]
        result = subprocess.run(
            command,
            cwd=dest,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        if result.returncode != 0:
            raise BlenderCandidateError("Blender candidate execution failed")
        for path in (glb, preview):
            if not path.is_file() or path.stat().st_size < 64:
                raise BlenderCandidateError("Blender candidate did not produce the required artifacts")
        version = str(self.preflight()["version"])
        artifact = BlenderArtifact(
            project_id=plan.project_id,
            blender_version=version,
            glb_path=glb.name,
            preview_path=preview.name,
            glb_sha256=_sha256(glb),
            preview_sha256=_sha256(preview),
            glb_bytes=glb.stat().st_size,
            preview_bytes=preview.stat().st_size,
        )
        manifest.write_text(
            json.dumps(artifact.snapshot(), sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        manifest.chmod(0o600)
        return artifact

    @staticmethod
    def _script(plan: BlenderScenePlan, glb: Path, preview: Path) -> str:
        payload = json.dumps(asdict(plan), sort_keys=True)
        return f'''import bpy, json, math\nfrom pathlib import Path\nP=json.loads({payload!r})\nOUT=Path({str(glb)!r})\nPREVIEW=Path({str(preview)!r})\nbpy.ops.object.select_all(action="SELECT")\nbpy.ops.object.delete(use_global=False)\nfor datablocks in (bpy.data.materials, bpy.data.images, bpy.data.cameras, bpy.data.lights):\n    pass\n# Deterministic generated texture, embedded in the GLB.\nsize=int(P["material"]["texture_size"])\nimg=bpy.data.images.new("AIOSGeneratedTexture", width=size, height=size, alpha=True)\npixels=[]\nbase=P["material"]["base_color"]\nfor y in range(size):\n    for x in range(size):\n        f=1.0 if (x+y)%2==0 else 0.55\n        pixels.extend([base[0]*f, base[1]*f, base[2]*f, base[3]])\nimg.pixels=list(pixels)\nimg.pack()\nmat=bpy.data.materials.new(P["material"]["name"])\nmat.use_nodes=True\nbsdf=mat.node_tree.nodes.get("Principled BSDF")\nbsdf.inputs["Metallic"].default_value=float(P["material"]["metallic"])\nbsdf.inputs["Roughness"].default_value=float(P["material"]["roughness"])\ntex=mat.node_tree.nodes.new("ShaderNodeTexImage")\ntex.image=img\nmat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])\n# Hero mesh with PBR material and a real keyframed animation.\nbpy.ops.mesh.primitive_cube_add(location=(0,0,1))\nhero=bpy.context.object\nhero.name="AIOS_Hero"\nhero.data.materials.append(mat)\nstart=int(P["animation"]["frame_start"]); end=int(P["animation"]["frame_end"])\nhero.location.x=0.0; hero.keyframe_insert(data_path="location", frame=start)\nhero.location.x=float(P["animation"]["travel_x"]); hero.keyframe_insert(data_path="location", frame=end)\n# Environment floor with its own PBR material.\nbpy.ops.mesh.primitive_plane_add(size=float(P["environment"]["ground_size"]), location=(0,0,0))\nground=bpy.context.object; ground.name="AIOS_Environment_Ground"\ngmat=bpy.data.materials.new("AIOS_Environment_Material"); gmat.use_nodes=True\ngbsdf=gmat.node_tree.nodes.get("Principled BSDF")\ngbsdf.inputs["Base Color"].default_value=(0.035,0.055,0.08,1.0)\ngbsdf.inputs["Roughness"].default_value=0.72\nground.data.materials.append(gmat)\n# Key/fill lights and governed world background.\ndef light(name, location, energy, size):\n    data=bpy.data.lights.new(name=name, type="AREA"); data.energy=energy; data.shape="DISK"; data.size=size\n    obj=bpy.data.objects.new(name, data); bpy.context.collection.objects.link(obj); obj.location=location\n    obj.rotation_euler=(math.radians(22),0,math.radians(145)); return obj\nlight("AIOS_Key", (4,-4,6), float(P["environment"]["key_light_energy"]), 5.0)\nlight("AIOS_Fill", (-4,2,3), float(P["environment"]["key_light_energy"])*0.35, 4.0)\nworld=bpy.context.scene.world or bpy.data.worlds.new("World")\nbpy.context.scene.world=world; world.use_nodes=True\nbg=world.node_tree.nodes.get("Background"); bg.inputs["Color"].default_value=(0.015,0.025,0.05,1.0); bg.inputs["Strength"].default_value=float(P["environment"]["world_strength"])\n# Camera and deterministic preview.\nbpy.ops.object.camera_add(location=(7,-8,5), rotation=(math.radians(67),0,math.radians(40)))\ncam=bpy.context.object; bpy.context.scene.camera=cam\ndef point_at(obj, target):\n    obj.rotation_euler=(target-obj.location).to_track_quat('-Z','Y').to_euler()\nfrom mathutils import Vector\npoint_at(cam, Vector((1.0,0.0,1.0)))\nscene=bpy.context.scene\nscene.frame_start=start; scene.frame_end=end; scene.frame_set((start+end)//2)\nscene.render.engine="BLENDER_EEVEE"\nscene.render.resolution_x=512; scene.render.resolution_y=384; scene.render.resolution_percentage=100\nscene.render.image_settings.file_format="PNG"; scene.render.filepath=str(PREVIEW)\nscene.render.film_transparent=False\nbpy.ops.export_scene.gltf(filepath=str(OUT), export_format="GLB", export_animations=True, export_materials="EXPORT")\nbpy.ops.render.render(write_still=True)\nprint("AIOS_PHASE36I_SCENE_OK")\n'''


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
