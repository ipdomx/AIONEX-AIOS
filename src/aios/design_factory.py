"""Phase 36E governed design/image planning and provider prompt compilation."""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Final


class DesignFactoryError(ValueError):
    """A design request cannot be represented by the governed contract."""


_HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {"generate", "edit", "variation", "inpaint", "background-remove"}
)
_ALLOWED_USE_CASES: Final[frozenset[str]] = frozenset(
    {
        "logo",
        "brand-system",
        "poster",
        "advertisement",
        "product-mockup",
        "infographic",
        "diagram",
        "experimental-graphic",
        "social-post",
    }
)


@dataclass(frozen=True, slots=True)
class DesignPreset:
    preset_id: str
    width: int
    height: int
    aspect_ratio: str
    category: str
    raster_exports: tuple[str, ...] = ("png", "webp", "jpeg")
    editable_export: str = "svg"


DESIGN_PRESETS: Final[dict[str, DesignPreset]] = {
    "logo-square": DesignPreset("logo-square", 1024, 1024, "1:1", "logo", ("png", "webp")),
    "social-square": DesignPreset("social-square", 1080, 1080, "1:1", "social"),
    "social-portrait": DesignPreset("social-portrait", 1080, 1350, "4:5", "social"),
    "story-vertical": DesignPreset("story-vertical", 1080, 1920, "9:16", "social"),
    "ad-landscape": DesignPreset("ad-landscape", 1200, 628, "1.91:1", "advertising"),
    "presentation-hd": DesignPreset("presentation-hd", 1920, 1080, "16:9", "presentation"),
    "visual-landscape": DesignPreset("visual-landscape", 1600, 900, "16:9", "visual"),
    "product-square": DesignPreset("product-square", 1600, 1600, "1:1", "product"),
    "poster-portrait": DesignPreset("poster-portrait", 1600, 2000, "4:5", "poster"),
    "infographic-portrait": DesignPreset("infographic-portrait", 1600, 2400, "2:3", "infographic"),
}


@dataclass(frozen=True, slots=True)
class BrandKit:
    name: str
    primary: str = "#1d4ed8"
    secondary: str = "#020617"
    accent: str = "#38bdf8"
    surface: str = "#ffffff"
    text: str = "#0f172a"
    fonts: tuple[str, ...] = ("Inter", "Arial", "sans-serif")
    voice: str = "clear, confident, modern"

    def __post_init__(self) -> None:
        if not self.name.strip() or len(self.name) > 120:
            raise DesignFactoryError("brand name is invalid")
        for value in (self.primary, self.secondary, self.accent, self.surface, self.text):
            if not _HEX_COLOR.fullmatch(value):
                raise DesignFactoryError("brand colors must use six-digit hex values")
        if not 1 <= len(self.fonts) <= 6 or any(not item.strip() for item in self.fonts):
            raise DesignFactoryError("brand font stack is invalid")

    @property
    def palette(self) -> tuple[str, ...]:
        return (self.primary, self.secondary, self.accent, self.surface, self.text)


@dataclass(frozen=True, slots=True)
class ImageProviderCapability:
    provider: str
    model: str
    operations: frozenset[str]
    max_resolution: int
    supports_transparency: bool = False
    supports_multiple_references: bool = False
    quality_score: float = 0.5
    latency_score: float = 0.5
    cost_score: float = 0.5
    stable: bool = True


IMAGE_PROVIDER_CAPABILITIES: Final[tuple[ImageProviderCapability, ...]] = (
    ImageProviderCapability(
        "openai",
        "gpt-image-2",
        frozenset({"generate", "edit", "variation", "inpaint", "background-remove"}),
        2048,
        supports_transparency=True,
        supports_multiple_references=True,
        quality_score=0.98,
        latency_score=0.82,
        cost_score=0.72,
    ),
    ImageProviderCapability(
        "gemini",
        "gemini-3.1-flash-image",
        frozenset({"generate", "edit", "variation"}),
        4096,
        supports_multiple_references=True,
        quality_score=0.97,
        latency_score=0.91,
        cost_score=0.86,
    ),
    ImageProviderCapability(
        "gemini",
        "gemini-3.1-flash-lite-image",
        frozenset({"generate", "edit", "variation"}),
        1024,
        supports_multiple_references=True,
        quality_score=0.88,
        latency_score=0.98,
        cost_score=0.98,
    ),
    ImageProviderCapability(
        "gemini",
        "gemini-3-pro-image",
        frozenset({"generate", "edit", "variation"}),
        4096,
        supports_multiple_references=True,
        quality_score=0.995,
        latency_score=0.66,
        cost_score=0.48,
    ),
    ImageProviderCapability(
        "fireworks",
        "flux-kontext-pro",
        frozenset({"generate", "edit", "variation"}),
        2048,
        supports_multiple_references=False,
        quality_score=0.91,
        latency_score=0.80,
        cost_score=0.77,
    ),
    ImageProviderCapability(
        "fireworks",
        "flux-kontext-max",
        frozenset({"generate", "edit", "variation"}),
        2048,
        supports_multiple_references=False,
        quality_score=0.95,
        latency_score=0.66,
        cost_score=0.58,
    ),
    ImageProviderCapability(
        "fireworks",
        "flux-1-schnell-fp8",
        frozenset({"generate"}),
        2048,
        quality_score=0.83,
        latency_score=0.97,
        cost_score=0.94,
    ),
)


@dataclass(frozen=True, slots=True)
class DesignRequest:
    title: str
    brief: str
    use_case: str
    preset_id: str
    operation: str = "generate"
    style: str = "modern"
    language: str = "en-US"
    target_audience: str = "general"
    exact_text: tuple[str, ...] = ()
    negative_constraints: tuple[str, ...] = ()
    transparent_background: bool = False
    reference_count: int = 0
    brand: BrandKit = field(default_factory=lambda: BrandKit("AIONEX"))

    def __post_init__(self) -> None:
        if not 2 <= len(self.title.strip()) <= 200:
            raise DesignFactoryError("design title is invalid")
        if not 8 <= len(self.brief.strip()) <= 12_000:
            raise DesignFactoryError("design brief is invalid")
        if self.use_case not in _ALLOWED_USE_CASES:
            raise DesignFactoryError("design use case is unsupported")
        if self.preset_id not in DESIGN_PRESETS:
            raise DesignFactoryError("design preset is unknown")
        if self.operation not in _ALLOWED_OPERATIONS:
            raise DesignFactoryError("design operation is unsupported")
        if not 0 <= self.reference_count <= 14:
            raise DesignFactoryError("design reference count is outside the allowed range")
        if len(self.exact_text) > 20 or any(len(item) > 500 for item in self.exact_text):
            raise DesignFactoryError("exact design text is outside the allowed range")
        if len(self.negative_constraints) > 30:
            raise DesignFactoryError("design constraints exceed the allowed range")


@dataclass(frozen=True, slots=True)
class CompiledDesignPrompt:
    provider: str
    model: str
    prompt: str
    negative_prompt: str | None
    settings: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DesignPlan:
    request: DesignRequest
    preset: DesignPreset
    provider_candidates: tuple[ImageProviderCapability, ...]
    compiled_prompts: tuple[CompiledDesignPrompt, ...]
    editable_source: str
    raster_exports: tuple[str, ...]
    render_status: str
    checksum: str

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "title": self.request.title,
            "use_case": self.request.use_case,
            "operation": self.request.operation,
            "preset": asdict(self.preset),
            "brand": {
                "name": self.request.brand.name,
                "palette": list(self.request.brand.palette),
                "fonts": list(self.request.brand.fonts),
                "voice": self.request.brand.voice,
            },
            "provider_candidates": [
                {
                    "provider": item.provider,
                    "model": item.model,
                    "max_resolution": item.max_resolution,
                    "stable": item.stable,
                }
                for item in self.provider_candidates
            ],
            "editable_source": self.editable_source,
            "raster_exports": list(self.raster_exports),
            "render_status": self.render_status,
            "checksum": self.checksum,
        }


def provider_candidates(request: DesignRequest) -> tuple[ImageProviderCapability, ...]:
    minimum_resolution = max(DESIGN_PRESETS[request.preset_id].width, DESIGN_PRESETS[request.preset_id].height)
    candidates = [
        item
        for item in IMAGE_PROVIDER_CAPABILITIES
        if request.operation in item.operations
        and item.max_resolution >= min(minimum_resolution, 4096)
        and (not request.transparent_background or item.supports_transparency)
        and (request.reference_count <= 1 or item.supports_multiple_references)
    ]
    candidates.sort(
        key=lambda item: (
            item.quality_score * 0.55 + item.latency_score * 0.25 + item.cost_score * 0.20,
            item.model,
        ),
        reverse=True,
    )
    if not candidates:
        raise DesignFactoryError("no launch image provider satisfies this design request")
    return tuple(candidates)


def _base_prompt(request: DesignRequest, preset: DesignPreset) -> str:
    text_rules = " | ".join(request.exact_text) if request.exact_text else "No mandatory copy."
    constraints = "; ".join(request.negative_constraints) if request.negative_constraints else "none"
    transparency = "transparent background" if request.transparent_background else "appropriate background"
    return (
        f"Create a production-quality {request.use_case}. "
        f"Title/concept: {request.title}. Brief: {request.brief}. "
        f"Audience: {request.target_audience}. Language: {request.language}. Style: {request.style}. "
        f"Brand: {request.brand.name}; palette {', '.join(request.brand.palette)}; "
        f"typography direction {', '.join(request.brand.fonts)}; voice {request.brand.voice}. "
        f"Canvas intent: {preset.width}x{preset.height} ({preset.aspect_ratio}); {transparency}. "
        f"Exact visible text when applicable: {text_rules}. "
        f"Avoid: {constraints}. Keep composition legible, balanced, export-safe, and brand-consistent."
    )


def compile_provider_prompt(
    request: DesignRequest, capability: ImageProviderCapability
) -> CompiledDesignPrompt:
    if request.operation not in capability.operations:
        raise DesignFactoryError("provider does not support the requested design operation")
    preset = DESIGN_PRESETS[request.preset_id]
    base = _base_prompt(request, preset)
    negative = ", ".join(request.negative_constraints) or None
    settings: dict[str, Any] = {
        "operation": request.operation,
        "aspect_ratio": preset.aspect_ratio,
        "target_width": preset.width,
        "target_height": preset.height,
    }
    prompt = base
    if capability.provider == "openai":
        settings.update(
            {
                "output_format": "png",
                "quality": "high",
                "background": "transparent" if request.transparent_background else "auto",
            }
        )
        negative = None
    elif capability.provider == "gemini":
        settings["image_size"] = "4K" if capability.max_resolution >= 4096 else "1K"
        if negative:
            prompt += f" Explicit exclusions: {negative}."
            negative = None
    elif capability.provider == "fireworks":
        settings["response_format"] = "binary"
    else:  # pragma: no cover - launch matrix is closed above
        raise DesignFactoryError("unsupported launch image provider")
    return CompiledDesignPrompt(
        provider=capability.provider,
        model=capability.model,
        prompt=prompt,
        negative_prompt=negative,
        settings=settings,
    )


def build_design_plan(request: DesignRequest) -> DesignPlan:
    preset = DESIGN_PRESETS[request.preset_id]
    candidates = provider_candidates(request)
    compiled = tuple(compile_provider_prompt(request, item) for item in candidates)
    canonical = {
        "request": asdict(request),
        "preset": asdict(preset),
        "providers": [
            {"provider": item.provider, "model": item.model, "operations": sorted(item.operations)}
            for item in candidates
        ],
    }
    checksum = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return DesignPlan(
        request=request,
        preset=preset,
        provider_candidates=candidates,
        compiled_prompts=compiled,
        editable_source="svg",
        raster_exports=preset.raster_exports,
        render_status="planned",
        checksum=checksum,
    )


def editable_svg_template(plan: DesignPlan) -> str:
    """Return an editable layout template; it is deliberately never labeled as rendered/final."""
    preset = plan.preset
    brand = plan.request.brand
    title = html.escape(plan.request.title)
    brief = html.escape(plan.request.brief[:240])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{preset.width}" height="{preset.height}" '
        f'viewBox="0 0 {preset.width} {preset.height}" data-aionex-status="template" '
        f'data-aionex-plan="{plan.checksum}">'
        f'<rect data-layer="background" width="100%" height="100%" fill="{brand.secondary}"/>'
        f'<circle data-layer="accent" cx="82%" cy="18%" r="18%" fill="{brand.accent}" opacity=".22"/>'
        f'<text data-layer="headline" x="7%" y="48%" fill="{brand.surface}" '
        f'font-family="{html.escape(brand.fonts[0])}" font-size="72" font-weight="700">{title}</text>'
        f'<text data-layer="brief" x="7%" y="58%" fill="{brand.surface}" opacity=".78" '
        f'font-family="{html.escape(brand.fonts[0])}" font-size="28">{brief}</text>'
        '</svg>'
    )


def prompt_pack_markdown(plan: DesignPlan) -> str:
    lines = [
        f"# {plan.request.title} — governed prompt pack",
        "",
        f"Plan checksum: `{plan.checksum}`",
        f"Use case: {plan.request.use_case}",
        f"Preset: {plan.preset.preset_id} ({plan.preset.width}x{plan.preset.height})",
        f"Render status: **{plan.render_status}** (not a rendered/final asset)",
        "",
    ]
    for item in plan.compiled_prompts:
        lines.extend(
            [
                f"## {item.provider} / {item.model}",
                "",
                item.prompt,
                "",
                f"Settings: `{json.dumps(item.settings, sort_keys=True)}`",
                "",
            ]
        )
    return "\n".join(lines)
