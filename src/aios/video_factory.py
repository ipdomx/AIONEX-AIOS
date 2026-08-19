"""Phase 36F governed video planning, continuity and provider compilation contracts.

This module is deliberately planning-only. It never claims that a provider video was
created, never arms provider spend, and never stores credentials or remote signed URLs.
Durable asynchronous provider execution is a later Phase 36F checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Final


class VideoFactoryError(ValueError):
    """A video request cannot be represented by the governed contract."""


_ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "text-to-video",
        "image-to-video",
        "logo-to-video",
        "reference-to-video",
        "edit",
        "extend",
        "remix",
    }
)
_ALLOWED_USE_CASES: Final[frozenset[str]] = frozenset(
    {"advertisement", "explainer", "product", "social", "cinematic", "logo-animation"}
)
_ALLOWED_ASPECT_RATIOS: Final[frozenset[str]] = frozenset({"16:9", "9:16"})
_ALLOWED_RESOLUTIONS: Final[frozenset[str]] = frozenset({"720p", "1080p", "4k"})
_ALLOWED_RUNTIME_STATES: Final[frozenset[str]] = frozenset(
    {"inventory_visible", "ready", "external_gate", "disabled", "unknown"}
)
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


@dataclass(frozen=True, slots=True)
class VideoProviderCapability:
    provider: str
    model: str
    operations: frozenset[str]
    aspect_ratios: frozenset[str]
    resolutions: frozenset[str]
    durations_seconds: tuple[int, ...]
    max_reference_images: int = 0
    native_audio: bool = False
    supports_stateful_editing: bool = False
    supports_extension: bool = False
    async_job: bool = True
    preview: bool = False

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.model.strip():
            raise VideoFactoryError("video provider identity is invalid")
        if not self.operations or any(item not in _ALLOWED_OPERATIONS for item in self.operations):
            raise VideoFactoryError("video provider operation is invalid")
        if not self.aspect_ratios or not self.aspect_ratios <= _ALLOWED_ASPECT_RATIOS:
            raise VideoFactoryError("video provider aspect ratio is invalid")
        if not self.resolutions or not self.resolutions <= _ALLOWED_RESOLUTIONS:
            raise VideoFactoryError("video provider resolution is invalid")
        if not self.durations_seconds or any(item <= 0 or item > 30 for item in self.durations_seconds):
            raise VideoFactoryError("video provider duration is invalid")
        if self.max_reference_images < 0 or self.max_reference_images > 10:
            raise VideoFactoryError("video provider reference-image limit is invalid")


VIDEO_PROVIDER_CAPABILITIES: Final[tuple[VideoProviderCapability, ...]] = (
    VideoProviderCapability(
        provider="openai",
        model="sora-2",
        operations=frozenset(
            {"text-to-video", "image-to-video", "logo-to-video", "reference-to-video", "remix"}
        ),
        aspect_ratios=frozenset({"16:9", "9:16"}),
        resolutions=frozenset({"720p"}),
        durations_seconds=(4, 8, 12),
        max_reference_images=1,
        native_audio=True,
    ),
    VideoProviderCapability(
        provider="openai",
        model="sora-2-pro",
        operations=frozenset(
            {"text-to-video", "image-to-video", "logo-to-video", "reference-to-video", "remix"}
        ),
        aspect_ratios=frozenset({"16:9", "9:16"}),
        resolutions=frozenset({"720p"}),
        durations_seconds=(4, 8, 12),
        max_reference_images=1,
        native_audio=True,
    ),
    VideoProviderCapability(
        provider="gemini",
        model="gemini-omni-flash-preview",
        operations=frozenset({"text-to-video", "image-to-video", "logo-to-video"}),
        aspect_ratios=frozenset({"16:9", "9:16"}),
        resolutions=frozenset({"720p"}),
        durations_seconds=(8,),
        max_reference_images=1,
        native_audio=True,
        supports_stateful_editing=True,
        preview=True,
    ),
    VideoProviderCapability(
        provider="gemini",
        model="veo-3.1-fast-generate-preview",
        operations=frozenset({"text-to-video", "image-to-video", "logo-to-video", "extend"}),
        aspect_ratios=frozenset({"16:9", "9:16"}),
        resolutions=frozenset({"720p", "1080p", "4k"}),
        durations_seconds=(4, 6, 8),
        max_reference_images=3,
        native_audio=True,
        supports_extension=True,
        preview=True,
    ),
    VideoProviderCapability(
        provider="gemini",
        model="veo-3.1-generate-preview",
        operations=frozenset(
            {"text-to-video", "image-to-video", "logo-to-video", "extend"}
        ),
        aspect_ratios=frozenset({"16:9", "9:16"}),
        resolutions=frozenset({"720p", "1080p", "4k"}),
        durations_seconds=(4, 6, 8),
        max_reference_images=3,
        native_audio=True,
        supports_extension=True,
        preview=True,
    ),
    VideoProviderCapability(
        provider="gemini",
        model="veo-3.1-lite-generate-preview",
        operations=frozenset({"text-to-video", "image-to-video", "logo-to-video"}),
        aspect_ratios=frozenset({"16:9", "9:16"}),
        resolutions=frozenset({"720p", "1080p"}),
        durations_seconds=(4, 6, 8),
        max_reference_images=1,
        native_audio=True,
        preview=True,
    ),
)


@dataclass(frozen=True, slots=True)
class VideoRuntimeEvidence:
    provider: str
    model: str
    state: str
    proven_operations: frozenset[str] = frozenset()
    reason: str = ""

    def __post_init__(self) -> None:
        if self.state not in _ALLOWED_RUNTIME_STATES:
            raise VideoFactoryError("video runtime evidence state is invalid")
        if any(item not in _ALLOWED_OPERATIONS for item in self.proven_operations):
            raise VideoFactoryError("video runtime evidence operation is invalid")
        if self.state == "ready" and not self.proven_operations:
            raise VideoFactoryError("ready video runtime evidence requires proven operations")
        if len(self.reason) > 500:
            raise VideoFactoryError("video runtime evidence reason is too long")


@dataclass(frozen=True, slots=True)
class VideoScene:
    scene_id: str
    purpose: str
    prompt: str
    duration_seconds: int
    narration: str | None = None
    reference_role: str | None = None
    transition: str = "cut"

    def __post_init__(self) -> None:
        scene_id = self.scene_id.strip().lower()
        if not _SAFE_ID.fullmatch(scene_id):
            raise VideoFactoryError("video scene id is invalid")
        if not 2 <= len(self.purpose.strip()) <= 160:
            raise VideoFactoryError("video scene purpose is invalid")
        if not 8 <= len(self.prompt.strip()) <= 4000:
            raise VideoFactoryError("video scene prompt is invalid")
        if self.duration_seconds not in {4, 6, 8, 12}:
            raise VideoFactoryError("video scene duration is unsupported")
        if self.reference_role is not None and self.reference_role not in {"logo", "image", "character", "product", "style"}:
            raise VideoFactoryError("video scene reference role is invalid")
        if self.transition not in {"cut", "fade", "crossfade", "match-cut"}:
            raise VideoFactoryError("video scene transition is invalid")
        if self.narration is not None and len(self.narration) > 2000:
            raise VideoFactoryError("video scene narration is too long")
        object.__setattr__(self, "scene_id", scene_id)


@dataclass(frozen=True, slots=True)
class VideoRequest:
    title: str
    brief: str
    operation: str = "text-to-video"
    use_case: str = "advertisement"
    aspect_ratio: str = "16:9"
    resolution: str = "720p"
    language: str = "en-US"
    style: str = "cinematic"
    target_audience: str = "general"
    reference_count: int = 0
    brand_name: str = "AIONEX"
    exact_text: tuple[str, ...] = ()
    negative_constraints: tuple[str, ...] = ()
    scenes: tuple[VideoScene, ...] = ()

    def __post_init__(self) -> None:
        if not 2 <= len(self.title.strip()) <= 200:
            raise VideoFactoryError("video title is invalid")
        if not 8 <= len(self.brief.strip()) <= 12000:
            raise VideoFactoryError("video brief is invalid")
        if self.operation not in _ALLOWED_OPERATIONS:
            raise VideoFactoryError("video operation is unsupported")
        if self.use_case not in _ALLOWED_USE_CASES:
            raise VideoFactoryError("video use case is unsupported")
        if self.aspect_ratio not in _ALLOWED_ASPECT_RATIOS:
            raise VideoFactoryError("video aspect ratio is unsupported")
        if self.resolution not in _ALLOWED_RESOLUTIONS:
            raise VideoFactoryError("video resolution is unsupported")
        if not 0 <= self.reference_count <= 3:
            raise VideoFactoryError("video reference count is outside the allowed range")
        if self.operation in {"image-to-video", "logo-to-video", "edit", "extend", "remix"} and self.reference_count != 1:
            raise VideoFactoryError("video operation requires exactly one governed reference")
        if self.operation == "reference-to-video" and not 1 <= self.reference_count <= 3:
            raise VideoFactoryError("reference-to-video requires one to three governed references")
        if self.operation == "text-to-video" and self.reference_count:
            raise VideoFactoryError("text-to-video cannot smuggle a reference")
        if len(self.exact_text) > 20 or any(len(item) > 500 for item in self.exact_text):
            raise VideoFactoryError("video exact text is outside the allowed range")
        if len(self.negative_constraints) > 30:
            raise VideoFactoryError("video constraints exceed the allowed range")
        if self.scenes and not 1 <= len(self.scenes) <= 100:
            raise VideoFactoryError("video scene count is outside the allowed range")
        if self.scenes and len({item.scene_id for item in self.scenes}) != len(self.scenes):
            raise VideoFactoryError("video scene ids must be unique")


@dataclass(frozen=True, slots=True)
class CompiledVideoScene:
    scene_id: str
    provider: str
    model: str
    endpoint_kind: str
    prompt: str
    settings: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VideoPlan:
    request: VideoRequest
    scenes: tuple[VideoScene, ...]
    provider_candidates: tuple[VideoProviderCapability, ...]
    compiled_scenes: tuple[CompiledVideoScene, ...]
    continuity_id: str
    render_status: str
    checksum: str

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36F.video-plan.v1",
            "render_status": self.render_status,
            "checksum": self.checksum,
            "continuity_id": self.continuity_id,
            "request": {
                "title": self.request.title,
                "operation": self.request.operation,
                "use_case": self.request.use_case,
                "aspect_ratio": self.request.aspect_ratio,
                "resolution": self.request.resolution,
                "language": self.request.language,
                "style": self.request.style,
                "target_audience": self.request.target_audience,
                "reference_count": self.request.reference_count,
                "brand_name": self.request.brand_name,
                "exact_text": list(self.request.exact_text),
                "negative_constraints": list(self.request.negative_constraints),
            },
            "scenes": [asdict(item) for item in self.scenes],
            "providers": [
                {
                    "provider": item.provider,
                    "model": item.model,
                    "preview": item.preview,
                    "async_job": item.async_job,
                    "native_audio": item.native_audio,
                }
                for item in self.provider_candidates
            ],
            "compiled_scenes": [asdict(item) for item in self.compiled_scenes],
        }


def default_ad_scenes(request: VideoRequest) -> tuple[VideoScene, ...]:
    reference_role = "logo" if request.operation == "logo-to-video" else "image" if request.reference_count else None
    exact = " | ".join(request.exact_text) if request.exact_text else "No mandatory visible copy."
    base = f"{request.brief} Brand: {request.brand_name}. Audience: {request.target_audience}. Style: {request.style}. Exact copy: {exact}"
    return (
        VideoScene(
            scene_id="opening",
            purpose="attention hook",
            prompt=f"Opening cinematic establishing shot. {base}",
            duration_seconds=4,
            reference_role=reference_role,
            transition="cut",
        ),
        VideoScene(
            scene_id="value",
            purpose="show core value",
            prompt=f"Demonstrate the core product or brand value with visual proof. {base}",
            duration_seconds=8,
            narration=request.brief[:800],
            reference_role=reference_role,
            transition="match-cut",
        ),
        VideoScene(
            scene_id="proof",
            purpose="detail and trust",
            prompt=f"Detail sequence that builds credibility without fabricating claims. {base}",
            duration_seconds=8,
            reference_role=reference_role,
            transition="crossfade",
        ),
        VideoScene(
            scene_id="close",
            purpose="resolution and call to action",
            prompt=f"Resolve the visual story with a memorable but truthful call to action. {base}",
            duration_seconds=4,
            reference_role=reference_role,
            transition="fade",
        ),
    )


def _capability_matches(capability: VideoProviderCapability, request: VideoRequest, scene: VideoScene) -> bool:
    if request.operation not in capability.operations:
        return False
    if request.aspect_ratio not in capability.aspect_ratios or request.resolution not in capability.resolutions:
        return False
    if scene.duration_seconds not in capability.durations_seconds:
        return False
    if request.reference_count > capability.max_reference_images:
        return False
    if request.operation == "extend" and not capability.supports_extension:
        return False
    return True


def provider_candidates(request: VideoRequest, scenes: tuple[VideoScene, ...]) -> tuple[VideoProviderCapability, ...]:
    candidates = tuple(
        item for item in VIDEO_PROVIDER_CAPABILITIES if all(_capability_matches(item, request, scene) for scene in scenes)
    )
    if not candidates:
        raise VideoFactoryError("no launch video provider supports the requested contract")
    return candidates


def _openai_size(request: VideoRequest) -> str:
    if request.resolution != "720p":
        raise VideoFactoryError("Sora 2 launch contract currently supports governed 720p create sizes only")
    return "1280x720" if request.aspect_ratio == "16:9" else "720x1280"


def compile_scene(request: VideoRequest, scene: VideoScene, capability: VideoProviderCapability) -> CompiledVideoScene:
    if not _capability_matches(capability, request, scene):
        raise VideoFactoryError("video provider does not support the scene contract")
    exclusions = ", ".join(request.negative_constraints) or "none"
    prompt = (
        f"{scene.prompt} Maintain continuity id {{continuity_id}} across the project. "
        f"Language: {request.language}. Avoid: {exclusions}. "
        "Preserve identity, wardrobe/product details, lighting logic and spatial continuity across adjacent shots."
    )
    settings: dict[str, Any]
    endpoint_kind: str
    if capability.provider == "openai":
        endpoint_kind = "openai-video-job"
        settings = {
            "endpoint": "/v1/videos",
            "model": capability.model,
            "seconds": scene.duration_seconds,
            "size": _openai_size(request),
            "reference_required": request.reference_count > 0,
            "async_job": True,
        }
    elif capability.provider == "gemini" and capability.model == "gemini-omni-flash-preview":
        endpoint_kind = "gemini-interaction-video"
        settings = {
            "model": capability.model,
            "response_format": "video",
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
            "task": request.operation,
            "duration_seconds": scene.duration_seconds,
            "reference_count": request.reference_count,
            "stateful": capability.supports_stateful_editing,
        }
    elif capability.provider == "gemini":
        endpoint_kind = "gemini-long-running-video"
        settings = {
            "model": capability.model,
            "operation": "generateVideos",
            "aspect_ratio": request.aspect_ratio,
            "resolution": request.resolution,
            "duration_seconds": scene.duration_seconds,
            "reference_count": request.reference_count,
            "async_job": True,
        }
    else:  # pragma: no cover - launch matrix is closed above
        raise VideoFactoryError("unsupported launch video provider")
    return CompiledVideoScene(
        scene_id=scene.scene_id,
        provider=capability.provider,
        model=capability.model,
        endpoint_kind=endpoint_kind,
        prompt=prompt,
        settings=settings,
    )


def build_video_plan(request: VideoRequest) -> VideoPlan:
    scenes = request.scenes or default_ad_scenes(request)
    candidates = provider_candidates(request, scenes)
    selected = candidates[0]
    canonical = {
        "request": asdict(request),
        "scenes": [asdict(item) for item in scenes],
        "selected_provider": {"provider": selected.provider, "model": selected.model},
    }
    seed = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    continuity_id = "vid-" + hashlib.sha256(seed).hexdigest()[:24]
    compiled = tuple(
        CompiledVideoScene(
            scene_id=item.scene_id,
            provider=(row := compile_scene(request, item, selected)).provider,
            model=row.model,
            endpoint_kind=row.endpoint_kind,
            prompt=row.prompt.replace("{continuity_id}", continuity_id),
            settings=row.settings,
        )
        for item in scenes
    )
    public = {
        "schema": "36F.video-plan.v1",
        "request": asdict(request),
        "scenes": [asdict(item) for item in scenes],
        "provider": {"provider": selected.provider, "model": selected.model},
        "continuity_id": continuity_id,
        "render_status": "planned",
    }
    checksum = hashlib.sha256(
        json.dumps(public, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return VideoPlan(
        request=request,
        scenes=scenes,
        provider_candidates=candidates,
        compiled_scenes=compiled,
        continuity_id=continuity_id,
        render_status="planned",
        checksum=checksum,
    )


def runtime_ready_provider(
    request: VideoRequest,
    *,
    evidence: tuple[VideoRuntimeEvidence, ...],
) -> VideoProviderCapability:
    """Return a provider only when operation-specific live evidence exists.

    Inventory visibility or static capability never means that a video provider is live-ready.
    """
    scenes = request.scenes or default_ad_scenes(request)
    candidates = provider_candidates(request, scenes)
    by_key = {(item.provider, item.model): item for item in evidence}
    for candidate in candidates:
        row = by_key.get((candidate.provider, candidate.model))
        if row is None or row.state != "ready" or request.operation not in row.proven_operations:
            continue
        return candidate
    raise VideoFactoryError("no live-proven video provider supports the requested contract")
