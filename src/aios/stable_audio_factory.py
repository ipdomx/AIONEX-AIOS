"""Phase 36G Stage 7D governed Stability Stable Audio 2.5 draft contracts.

This source contract intentionally exposes only the currently funded, predictable
text-to-audio draft route. It performs no provider request. Full-song/vocal/stem
claims remain outside this stage.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Final


class StableAudioFactoryError(ValueError):
    """A Stable Audio request cannot satisfy the bounded Stage 7D contract."""


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE = re.compile(r"^[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]{2,8})*$")
_FORBIDDEN_STYLE_REFERENCES: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bin\s+the\s+style\s+of\b",
        r"\bsounds?\s+like\b",
        r"\bsing\s+like\b",
        r"\bvoice\s+of\b",
        r"\bimitate\b",
        r"\bimpersonate\b",
    )
)
_ALLOWED_OUTPUT_PROFILES: Final[frozenset[str]] = frozenset(
    {
        "wav-pcm-48k-stereo",
        "m4a-aac-48k-stereo",
        "webm-opus-48k-stereo",
    }
)


@dataclass(frozen=True, slots=True)
class StableAudioRoute:
    provider: str = "stability"
    model: str = "stable-audio-2.5"
    tier: str = "draft"
    fixed_cost_usd: float = 0.20
    credits_per_success: int = 20
    credit_usd: float = 0.01
    duration_seconds: int = 30
    provider_output_media_type: str = "audio/mpeg"
    provider_sample_rate_hz: int = 44_100
    provider_channels: int = 2
    preview: bool = False

    def __post_init__(self) -> None:
        if self.provider != "stability" or self.model != "stable-audio-2.5":
            raise StableAudioFactoryError("Stable Audio provider/model route is invalid")
        if self.tier != "draft":
            raise StableAudioFactoryError("Stage 7D exposes draft generation only")
        if self.fixed_cost_usd != 0.20 or self.credits_per_success != 20:
            raise StableAudioFactoryError("Stable Audio fixed cost is outside the approved route")
        if self.credit_usd != 0.01:
            raise StableAudioFactoryError("Stable Audio credit valuation is invalid")
        if self.duration_seconds != 30:
            raise StableAudioFactoryError("Stage 7D duration must remain 30 seconds")
        if self.provider_output_media_type != "audio/mpeg":
            raise StableAudioFactoryError("Stable Audio provider output must be MP3")
        if self.provider_sample_rate_hz != 44_100 or self.provider_channels != 2:
            raise StableAudioFactoryError("Stable Audio provider audio profile is invalid")
        if self.preview:
            raise StableAudioFactoryError("Stable Audio 2.5 must not be mislabeled preview")


STABLE_AUDIO_25_ROUTE: Final[StableAudioRoute] = StableAudioRoute()


@dataclass(frozen=True, slots=True)
class StableAudioRightsEvidence:
    commercial_use_authorized: bool
    user_accepts_provider_terms: bool
    ai_generated_disclosure_required: bool = True

    def __post_init__(self) -> None:
        if not self.commercial_use_authorized:
            raise StableAudioFactoryError("commercial use must be explicitly authorized")
        if not self.user_accepts_provider_terms:
            raise StableAudioFactoryError("provider terms must be explicitly accepted")
        if not self.ai_generated_disclosure_required:
            raise StableAudioFactoryError("AI-generated disclosure cannot be disabled")

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "basis": "instrumental",
            "commercial_use_authorized": True,
            "provider_terms_accepted": True,
            "ai_generated_disclosure_required": True,
            "synthid_disclosure_required": False,
        }


@dataclass(frozen=True, slots=True)
class StableAudioRequest:
    title: str
    prompt: str
    language: str
    rights: StableAudioRightsEvidence
    output_profile_id: str = "wav-pcm-48k-stereo"
    instrumental_only: bool = True
    duration_seconds: int = 30
    max_attempts: int = 1

    def __post_init__(self) -> None:
        title = self.title.strip()
        prompt = self.prompt.strip()
        if not 2 <= len(title) <= 200:
            raise StableAudioFactoryError("Stable Audio title is invalid")
        if not 8 <= len(prompt) <= 10_000 or "\x00" in prompt:
            raise StableAudioFactoryError("Stable Audio prompt is invalid")
        if not _LANGUAGE.fullmatch(self.language):
            raise StableAudioFactoryError("Stable Audio language is invalid")
        if self.output_profile_id not in _ALLOWED_OUTPUT_PROFILES:
            raise StableAudioFactoryError("Stable Audio output profile is unsupported")
        if not self.instrumental_only:
            raise StableAudioFactoryError("Stage 7D does not claim vocal generation")
        if self.duration_seconds != 30:
            raise StableAudioFactoryError("Stage 7D request duration must be 30 seconds")
        if self.max_attempts != 1:
            raise StableAudioFactoryError("Stable Audio generation must use one attempt")
        if any(pattern.search(prompt) for pattern in _FORBIDDEN_STYLE_REFERENCES):
            raise StableAudioFactoryError("named-person or imitation references are forbidden")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "prompt", prompt)


@dataclass(frozen=True, slots=True)
class StableAudioCostPolicy:
    request_cap_usd: float = 0.20
    monthly_user_cap_usd: float = 0.40
    max_generations_per_month: int = 2
    max_attempts: int = 1
    automatic_retry: bool = False
    automatic_cross_provider_fallback: bool = False

    def __post_init__(self) -> None:
        if self.request_cap_usd != 0.20:
            raise StableAudioFactoryError("Stable Audio request cap must remain $0.20")
        if self.monthly_user_cap_usd != 0.40:
            raise StableAudioFactoryError("music monthly cap must remain $0.40")
        if self.max_generations_per_month != 2:
            raise StableAudioFactoryError("Stable Audio monthly generation count is invalid")
        if self.max_attempts != 1 or self.automatic_retry:
            raise StableAudioFactoryError("Stable Audio retry policy cannot be relaxed")
        if self.automatic_cross_provider_fallback:
            raise StableAudioFactoryError("cross-provider fallback after arming is forbidden")

    def public_snapshot(self) -> dict[str, Any]:
        return asdict(self)


STABLE_AUDIO_LOW_COST_POLICY: Final[StableAudioCostPolicy] = StableAudioCostPolicy()


@dataclass(frozen=True, slots=True)
class StableAudioPlan:
    request: StableAudioRequest
    route: StableAudioRoute
    cost_policy: StableAudioCostPolicy
    estimated_cost_usd: float
    max_cost_usd: float
    plan_status: str
    render_status: str
    external_gates: tuple[str, ...]
    checksum: str

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36G.stable-audio-plan.v1",
            "checksum": self.checksum,
            "plan_status": self.plan_status,
            "render_status": self.render_status,
            "provider": self.route.provider,
            "model": self.route.model,
            "tier": self.route.tier,
            "preview_model": False,
            "fixed_cost_usd": self.route.fixed_cost_usd,
            "credits_per_success": self.route.credits_per_success,
            "credit_usd": self.route.credit_usd,
            "estimated_cost_usd": self.estimated_cost_usd,
            "max_cost_usd": self.max_cost_usd,
            "cost_policy": self.cost_policy.public_snapshot(),
            "max_attempts": 1,
            "automatic_retry": False,
            "automatic_cross_provider_fallback": False,
            "output_profile_id": self.request.output_profile_id,
            "provider_output": {
                "media_type": self.route.provider_output_media_type,
                "sample_rate_hz": self.route.provider_sample_rate_hz,
                "channels": self.route.provider_channels,
                "duration_seconds": self.route.duration_seconds,
            },
            "content": {
                "title": self.request.title,
                "language": self.request.language,
                "instrumental_only": True,
                "prompt_sha256": hashlib.sha256(
                    self.request.prompt.encode("utf-8")
                ).hexdigest(),
                "prompt_characters": len(self.request.prompt),
                "raw_prompt_returned": False,
                "raw_lyrics_returned": False,
            },
            "rights": self.request.rights.public_snapshot(),
            "external_gates": list(self.external_gates),
            "music_generation_requests": 0,
            "provider_spend_usd": 0.0,
        }


def build_stable_audio_plan(
    request: StableAudioRequest,
    *,
    policy: StableAudioCostPolicy = STABLE_AUDIO_LOW_COST_POLICY,
) -> StableAudioPlan:
    route = STABLE_AUDIO_25_ROUTE
    canonical = {
        "request": asdict(request),
        "route": asdict(route),
        "policy": asdict(policy),
        "external_gates": (
            "valid-funded-stability-credential",
            "stable-audio-2.5-runtime-evidence",
            "music-rights-and-ai-generated-disclosure",
        ),
    }
    checksum = hashlib.sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return StableAudioPlan(
        request=request,
        route=route,
        cost_policy=policy,
        estimated_cost_usd=route.fixed_cost_usd,
        max_cost_usd=route.fixed_cost_usd,
        plan_status="external_gate",
        render_status="not_started",
        external_gates=tuple(canonical["external_gates"]),
        checksum=checksum,
    )
