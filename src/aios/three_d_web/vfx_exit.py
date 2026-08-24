"""Phase 36I governed VFX and final interactive-media exit contracts.

The module is deterministic and side-effect free. Runtime execution is performed by
approved FFmpeg/glTF/browser adapters and represented here by evidence receipts.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from .contracts import PerformanceProfile
from .performance import PerformanceGateResult


class Phase36IExitError(ValueError):
    """Phase 36I evidence is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class VFXCompositePlan:
    width: int = 1280
    height: int = 720
    fps: int = 30
    duration_seconds: float = 3.0
    chroma_key: str = "0x00ff00"
    output_codec: str = "h264"

    def validate(self) -> None:
        if (self.width, self.height) not in {(1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)}:
            raise Phase36IExitError("VFX output resolution is outside governed profiles")
        if self.fps not in {24, 25, 30, 50, 60}:
            raise Phase36IExitError("VFX frame rate is outside governed profiles")
        if not 1.0 <= self.duration_seconds <= 60.0:
            raise Phase36IExitError("VFX acceptance duration must be between 1 and 60 seconds")
        if self.output_codec != "h264":
            raise Phase36IExitError("VFX acceptance requires governed H.264 output")

    def snapshot(self) -> dict[str, object]:
        self.validate()
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "duration_seconds": self.duration_seconds,
            "chroma_key": self.chroma_key,
            "output_codec": self.output_codec,
            "requires_ffmpeg9": True,
            "network_required": False,
        }


@dataclass(frozen=True, slots=True)
class VFXRuntimeEvidence:
    ffmpeg_version: str
    output_sha256: str
    output_bytes: int
    width: int
    height: int
    fps: float
    duration_seconds: float
    codec: str
    frames: int
    chroma_key_applied: bool
    overlay_applied: bool
    network_used: bool
    provider_used: bool

    def validate(self, plan: VFXCompositePlan) -> None:
        plan.validate()
        if self.ffmpeg_version != "9.0":
            raise Phase36IExitError("VFX evidence must come from FFmpeg 9.0")
        if len(self.output_sha256) != 64:
            raise Phase36IExitError("VFX output SHA-256 is invalid")
        if self.output_bytes <= 0 or self.frames <= 0:
            raise Phase36IExitError("VFX output is empty")
        if (self.width, self.height) != (plan.width, plan.height):
            raise Phase36IExitError("VFX output resolution does not match plan")
        if abs(self.fps - plan.fps) > 0.01:
            raise Phase36IExitError("VFX output frame rate does not match plan")
        if self.duration_seconds < plan.duration_seconds - 0.1:
            raise Phase36IExitError("VFX output duration is shorter than plan")
        if self.codec != "h264" or not self.chroma_key_applied or not self.overlay_applied:
            raise Phase36IExitError("VFX compositing stages are incomplete")
        if self.network_used or self.provider_used:
            raise Phase36IExitError("local VFX acceptance must not use network/provider execution")


@dataclass(frozen=True, slots=True)
class LODCompressionEvidence:
    source_sha256: str
    desktop_sha256: str
    mobile_sha256: str
    low_power_sha256: str
    source_bytes: int
    desktop_bytes: int
    mobile_bytes: int
    low_power_bytes: int
    meshopt_present: bool
    network_used: bool

    def validate(self) -> None:
        digests = (self.source_sha256, self.desktop_sha256, self.mobile_sha256, self.low_power_sha256)
        if any(len(value) != 64 for value in digests):
            raise Phase36IExitError("LOD evidence contains invalid SHA-256")
        sizes = (self.source_bytes, self.desktop_bytes, self.mobile_bytes, self.low_power_bytes)
        if any(value <= 0 for value in sizes):
            raise Phase36IExitError("LOD evidence contains empty artifacts")
        if not self.meshopt_present:
            raise Phase36IExitError("LOD artifacts must include Meshopt compression")
        if self.network_used:
            raise Phase36IExitError("LOD acceptance must not require network access")


@dataclass(frozen=True, slots=True)
class Phase36IExitDecision:
    passed: bool
    local_complete: bool
    external_gate_preserved: bool
    reasons: tuple[str, ...]
    receipt_sha256: str


class Phase36IExitGate:
    """Close local 36I work while preserving physical XR-device validation."""

    def evaluate(
        self,
        *,
        vfx: VFXRuntimeEvidence,
        vfx_plan: VFXCompositePlan,
        lod: LODCompressionEvidence,
        performance_results: tuple[PerformanceGateResult, ...],
        browser_qa_passed: bool,
        blender_3d_passed: bool,
        two_d_passed: bool,
        webxr_secure_context_passed: bool,
        physical_xr_device_tested: bool,
    ) -> Phase36IExitDecision:
        reasons: list[str] = []
        try:
            vfx.validate(vfx_plan)
        except Phase36IExitError as exc:
            reasons.append(str(exc))
        try:
            lod.validate()
        except Phase36IExitError as exc:
            reasons.append(str(exc))
        required = {PerformanceProfile.DESKTOP, PerformanceProfile.MOBILE, PerformanceProfile.LOW_POWER}
        seen = {item.profile for item in performance_results}
        if seen != required:
            reasons.append("all desktop/mobile/low_power performance profiles are required")
        if any(not item.passed for item in performance_results):
            reasons.append("one or more performance profiles failed")
        if not browser_qa_passed:
            reasons.append("browser QA did not pass")
        if not blender_3d_passed:
            reasons.append("Blender 3D runtime acceptance did not pass")
        if not two_d_passed:
            reasons.append("2D animation/game runtime acceptance did not pass")
        if not webxr_secure_context_passed:
            reasons.append("WebXR secure-context delivery did not pass")
        local_complete = not reasons
        payload = {
            "local_complete": local_complete,
            "physical_xr_device_tested": physical_xr_device_tested,
            "reasons": reasons,
            "profiles": sorted(item.profile.value for item in performance_results),
            "vfx_sha256": vfx.output_sha256,
            "lod": {
                "desktop": lod.desktop_sha256,
                "mobile": lod.mobile_sha256,
                "low_power": lod.low_power_sha256,
            },
        }
        receipt = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return Phase36IExitDecision(
            passed=local_complete,
            local_complete=local_complete,
            external_gate_preserved=not physical_xr_device_tested,
            reasons=tuple(reasons),
            receipt_sha256=receipt,
        )
