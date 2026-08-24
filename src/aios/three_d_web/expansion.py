"""Phase 36I interactive-media production foundation.

The module extends the existing 3D web contracts without pretending that an
external renderer, XR device, or VFX runtime has executed. It is side-effect
free except for the explicit bounded local Blender version probe.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit

BLENDER_PRODUCTION_BASELINE = "5.2.0"
THREE_JS_PRODUCTION_BASELINE = "0.185.1"


class InteractiveFoundationError(ValueError):
    """The requested interactive-media plan violates a production boundary."""


class InteractiveTarget(str, Enum):
    TWO_D_ANIMATION = "2d-animation"
    TWO_D_GAME = "2d-game"
    THREE_D_SCENE = "3d-scene"
    WEBXR_AR = "webxr-ar"
    WEBXR_VR = "webxr-vr"
    VFX_COMPOSITE = "vfx-composite"


@dataclass(frozen=True, slots=True)
class RendererProbe:
    executable: str
    version: str
    production_baseline: str = BLENDER_PRODUCTION_BASELINE

    @property
    def production_approved(self) -> bool:
        return _version_tuple(self.version) >= _version_tuple(self.production_baseline)

    def snapshot(self) -> dict[str, object]:
        return {
            "renderer": "blender",
            "executable_name": Path(self.executable).name,
            "version": self.version,
            "production_baseline": self.production_baseline,
            "production_approved": self.production_approved,
            "network_used": False,
        }


@dataclass(frozen=True, slots=True)
class DeliveryBoundary:
    public_origin: str
    application_tunnel_present: bool

    def __post_init__(self) -> None:
        parsed = urlsplit(self.public_origin.strip())
        if parsed.scheme != "https" or not parsed.hostname:
            raise InteractiveFoundationError("interactive delivery requires an HTTPS origin")
        if parsed.username or parsed.password or parsed.fragment:
            raise InteractiveFoundationError("interactive origin must not embed credentials or fragments")
        object.__setattr__(self, "public_origin", self.public_origin.rstrip("/"))

    def snapshot(self) -> dict[str, object]:
        return {
            "public_origin": self.public_origin,
            "secure_context": True,
            "application_tunnel_present": self.application_tunnel_present,
            "https_webgl_delivery_supported": self.application_tunnel_present,
            "https_webxr_delivery_supported": self.application_tunnel_present,
            "direct_udp_turn_certified_by_tunnel": False,
        }


@dataclass(frozen=True, slots=True)
class InteractiveProductionPlan:
    target: InteractiveTarget
    template: str
    outputs: tuple[str, ...]
    requires_blender: bool
    requires_three_js: bool
    requires_secure_context: bool
    requires_xr_device_acceptance: bool
    requires_video_compositor: bool
    lod_required: bool
    compression_required: bool
    current_three_js: str | None
    target_three_js: str | None

    @property
    def three_js_migration_required(self) -> bool:
        return bool(
            self.requires_three_js
            and self.current_three_js
            and self.target_three_js
            and self.current_three_js != self.target_three_js
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "target": self.target.value,
            "template": self.template,
            "outputs": list(self.outputs),
            "requires_blender": self.requires_blender,
            "requires_three_js": self.requires_three_js,
            "requires_secure_context": self.requires_secure_context,
            "requires_xr_device_acceptance": self.requires_xr_device_acceptance,
            "requires_video_compositor": self.requires_video_compositor,
            "lod_required": self.lod_required,
            "compression_required": self.compression_required,
            "current_three_js": self.current_three_js,
            "target_three_js": self.target_three_js,
            "three_js_migration_required": self.three_js_migration_required,
            "runtime_executed": False,
        }


class InteractiveProductionPlanner:
    """Deterministic planner for the six Phase 36I production families."""

    def __init__(self, *, current_three_js: str | None = None) -> None:
        self._current_three_js = current_three_js

    def plan(self, target: InteractiveTarget) -> InteractiveProductionPlan:
        table: dict[InteractiveTarget, dict[str, object]] = {
            InteractiveTarget.TWO_D_ANIMATION: {
                "template": "canvas-timeline-animation",
                "outputs": ("html", "javascript", "sprite-atlas", "preview-video"),
                "requires_blender": False,
                "requires_three_js": False,
                "requires_secure_context": False,
                "requires_xr_device_acceptance": False,
                "requires_video_compositor": True,
                "lod_required": False,
                "compression_required": True,
            },
            InteractiveTarget.TWO_D_GAME: {
                "template": "canvas-game-loop",
                "outputs": ("html", "javascript", "sprite-atlas", "game-manifest"),
                "requires_blender": False,
                "requires_three_js": False,
                "requires_secure_context": False,
                "requires_xr_device_acceptance": False,
                "requires_video_compositor": False,
                "lod_required": False,
                "compression_required": True,
            },
            InteractiveTarget.THREE_D_SCENE: {
                "template": "threejs-production-scene",
                "outputs": ("html", "javascript", "glb", "artifact-manifest"),
                "requires_blender": True,
                "requires_three_js": True,
                "requires_secure_context": False,
                "requires_xr_device_acceptance": False,
                "requires_video_compositor": False,
                "lod_required": True,
                "compression_required": True,
            },
            InteractiveTarget.WEBXR_AR: {
                "template": "threejs-webxr-ar",
                "outputs": ("html", "javascript", "glb", "xr-manifest"),
                "requires_blender": True,
                "requires_three_js": True,
                "requires_secure_context": True,
                "requires_xr_device_acceptance": True,
                "requires_video_compositor": False,
                "lod_required": True,
                "compression_required": True,
            },
            InteractiveTarget.WEBXR_VR: {
                "template": "threejs-webxr-vr",
                "outputs": ("html", "javascript", "glb", "xr-manifest"),
                "requires_blender": True,
                "requires_three_js": True,
                "requires_secure_context": True,
                "requires_xr_device_acceptance": True,
                "requires_video_compositor": False,
                "lod_required": True,
                "compression_required": True,
            },
            InteractiveTarget.VFX_COMPOSITE: {
                "template": "ffmpeg-vfx-composite",
                "outputs": ("video", "provenance-manifest", "qa-receipt"),
                "requires_blender": False,
                "requires_three_js": False,
                "requires_secure_context": False,
                "requires_xr_device_acceptance": False,
                "requires_video_compositor": True,
                "lod_required": False,
                "compression_required": True,
            },
        }
        item = table[target]
        needs_three = bool(item["requires_three_js"])
        outputs = item["outputs"]
        if not isinstance(outputs, tuple):
            raise InteractiveFoundationError("interactive outputs must be immutable")
        return InteractiveProductionPlan(
            target=target,
            template=str(item["template"]),
            outputs=tuple(str(value) for value in outputs),
            requires_blender=bool(item["requires_blender"]),
            requires_three_js=needs_three,
            requires_secure_context=bool(item["requires_secure_context"]),
            requires_xr_device_acceptance=bool(item["requires_xr_device_acceptance"]),
            requires_video_compositor=bool(item["requires_video_compositor"]),
            lod_required=bool(item["lod_required"]),
            compression_required=bool(item["compression_required"]),
            current_three_js=self._current_three_js if needs_three else None,
            target_three_js=THREE_JS_PRODUCTION_BASELINE if needs_three else None,
        )

    def all_plans(self) -> tuple[InteractiveProductionPlan, ...]:
        return tuple(self.plan(target) for target in InteractiveTarget)


def probe_blender(executable: str = "blender", *, timeout_seconds: int = 15) -> RendererProbe:
    if timeout_seconds < 1 or timeout_seconds > 60:
        raise InteractiveFoundationError("Blender probe timeout must be between 1 and 60 seconds")
    env = {key: os.environ[key] for key in ("LANG", "LC_ALL", "TZ") if key in os.environ}
    env.update({"HOME": "/tmp", "NO_COLOR": "1"})
    try:
        result = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InteractiveFoundationError("Blender executable is unavailable for bounded preflight") from exc
    if result.returncode != 0:
        raise InteractiveFoundationError("Blender version preflight failed")
    first_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
    match = re.fullmatch(r"Blender\s+(\d+\.\d+\.\d+)(?:\s+LTS)?", first_line.strip())
    if match is None:
        raise InteractiveFoundationError("Blender version output is not recognized")
    return RendererProbe(executable=executable, version=match.group(1))


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if match is None:
        raise InteractiveFoundationError("renderer version must be semantic x.y.z")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)
