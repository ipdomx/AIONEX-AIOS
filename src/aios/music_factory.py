"""Phase 36G Stage 7 governed low-cost music-generation contracts.

The contract deliberately separates a cheap 30-second draft from a full-song final
request.  It performs no network call and exposes only hashes in its public
snapshot.  Lyria 3 remains a preview provider route and can never become
``production_ready`` from this module alone.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Final


class MusicFactoryError(ValueError):
    """A music request cannot satisfy the governed low-cost contract."""


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
_ALLOWED_TIERS: Final[frozenset[str]] = frozenset({"draft", "final"})
_ALLOWED_RIGHTS_BASES: Final[frozenset[str]] = frozenset(
    {"instrumental", "original-user-owned", "licensed", "public-domain"}
)
_ALLOWED_OUTPUT_PROFILES: Final[frozenset[str]] = frozenset(
    {
        "wav-pcm-48k-stereo",
        "m4a-aac-48k-stereo",
        "webm-opus-48k-stereo",
    }
)


@dataclass(frozen=True, slots=True)
class LyriaCostRoute:
    tier: str
    model: str
    fixed_cost_usd: float
    nominal_duration_seconds: int | None
    provider_output_media_type: str = "audio/mpeg"
    provider_sample_rate_hz: int = 44_100
    provider_channels: int = 2
    preview: bool = True

    def __post_init__(self) -> None:
        if self.tier not in _ALLOWED_TIERS:
            raise MusicFactoryError("music tier is invalid")
        if not self.model.startswith("lyria-3-"):
            raise MusicFactoryError("music model is outside the Lyria 3 launch route")
        if self.fixed_cost_usd not in {0.04, 0.08}:
            raise MusicFactoryError("music fixed cost is outside the approved launch pricing")
        if self.provider_output_media_type != "audio/mpeg":
            raise MusicFactoryError("Lyria provider output must be MP3")
        if self.provider_sample_rate_hz != 44_100 or self.provider_channels != 2:
            raise MusicFactoryError("Lyria provider audio profile is invalid")
        if not self.preview:
            raise MusicFactoryError("Stage 7 launch models must remain preview-gated")


LYRIA_COST_ROUTES: Final[dict[str, LyriaCostRoute]] = {
    "draft": LyriaCostRoute(
        tier="draft",
        model="lyria-3-clip-preview",
        fixed_cost_usd=0.04,
        nominal_duration_seconds=30,
    ),
    "final": LyriaCostRoute(
        tier="final",
        model="lyria-3-pro-preview",
        fixed_cost_usd=0.08,
        nominal_duration_seconds=None,
    ),
}


@dataclass(frozen=True, slots=True)
class MusicRightsEvidence:
    basis: str
    evidence_sha256: str | None
    commercial_use_authorized: bool
    user_accepts_provider_terms: bool
    synthid_disclosure_required: bool = True

    def __post_init__(self) -> None:
        if self.basis not in _ALLOWED_RIGHTS_BASES:
            raise MusicFactoryError("music rights basis is invalid")
        if self.basis == "instrumental":
            if self.evidence_sha256 is not None:
                raise MusicFactoryError("instrumental rights evidence must not claim lyric rights")
        elif self.evidence_sha256 is None or not _SHA256.fullmatch(self.evidence_sha256):
            raise MusicFactoryError("lyric rights evidence checksum is required")
        if not self.commercial_use_authorized:
            raise MusicFactoryError("commercial use must be explicitly authorized")
        if not self.user_accepts_provider_terms:
            raise MusicFactoryError("provider terms must be explicitly accepted")
        if not self.synthid_disclosure_required:
            raise MusicFactoryError("SynthID disclosure cannot be disabled")

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "evidence_sha256": self.evidence_sha256,
            "commercial_use_authorized": True,
            "provider_terms_accepted": True,
            "synthid_disclosure_required": True,
        }


@dataclass(frozen=True, slots=True)
class MusicRequest:
    title: str
    prompt: str
    language: str
    rights: MusicRightsEvidence
    tier: str = "draft"
    instrumental_only: bool = True
    lyrics: str = ""
    output_profile_id: str = "wav-pcm-48k-stereo"
    final_generation_approved: bool = False
    final_approval_evidence_sha256: str | None = None
    prior_draft_checksum: str | None = None
    max_attempts: int = 1

    def __post_init__(self) -> None:
        title = self.title.strip()
        prompt = self.prompt.strip()
        lyrics = self.lyrics.strip()
        if not 2 <= len(title) <= 200:
            raise MusicFactoryError("music title is invalid")
        if not 8 <= len(prompt) <= 12_000 or "\x00" in prompt:
            raise MusicFactoryError("music prompt is invalid")
        if not _LANGUAGE.fullmatch(self.language):
            raise MusicFactoryError("music language is invalid")
        if self.tier not in _ALLOWED_TIERS:
            raise MusicFactoryError("music tier is invalid")
        if self.output_profile_id not in _ALLOWED_OUTPUT_PROFILES:
            raise MusicFactoryError("music output profile is unsupported")
        if self.max_attempts != 1:
            raise MusicFactoryError("music generation must use exactly one attempt")
        if any(pattern.search(prompt) for pattern in _FORBIDDEN_STYLE_REFERENCES):
            raise MusicFactoryError("named-person or imitation style references are forbidden")
        if self.instrumental_only:
            if lyrics:
                raise MusicFactoryError("instrumental request cannot include lyrics")
            if self.rights.basis != "instrumental":
                raise MusicFactoryError("instrumental request requires instrumental rights basis")
        else:
            if not 1 <= len(lyrics) <= 20_000 or "\x00" in lyrics:
                raise MusicFactoryError("governed lyrics are required for vocal music")
            if self.rights.basis == "instrumental":
                raise MusicFactoryError("vocal music requires governed lyric rights")
        if self.tier == "draft":
            if (
                self.final_generation_approved
                or self.final_approval_evidence_sha256 is not None
                or self.prior_draft_checksum is not None
            ):
                raise MusicFactoryError("draft route cannot claim final approval")
        else:
            if not self.final_generation_approved:
                raise MusicFactoryError("full-song generation requires explicit final approval")
            if (
                self.final_approval_evidence_sha256 is None
                or not _SHA256.fullmatch(self.final_approval_evidence_sha256)
            ):
                raise MusicFactoryError("full-song generation requires approval evidence")
            if self.prior_draft_checksum is None or not _SHA256.fullmatch(
                self.prior_draft_checksum
            ):
                raise MusicFactoryError("full-song generation requires an accepted draft checksum")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "lyrics", lyrics)


@dataclass(frozen=True, slots=True)
class MusicCostPolicy:
    default_tier: str = "draft"
    max_attempts: int = 1
    draft_first_required: bool = True
    full_song_requires_approval: bool = True
    automatic_retry: bool = False
    default_user_request_cap_usd: float = 0.04
    final_user_request_cap_usd: float = 0.08
    monthly_user_cap_usd: float = 0.40
    max_drafts_per_month: int = 10
    max_final_generations_per_month: int = 3

    def __post_init__(self) -> None:
        if self.default_tier != "draft" or self.max_attempts != 1:
            raise MusicFactoryError("low-cost music defaults cannot be relaxed")
        if not self.draft_first_required or not self.full_song_requires_approval:
            raise MusicFactoryError("draft-first and final approval are mandatory")
        if self.automatic_retry:
            raise MusicFactoryError("automatic music retry is forbidden")
        if self.default_user_request_cap_usd != 0.04:
            raise MusicFactoryError("draft user cap must match official fixed price")
        if self.final_user_request_cap_usd != 0.08:
            raise MusicFactoryError("final user cap must match official fixed price")
        if self.monthly_user_cap_usd != 0.40:
            raise MusicFactoryError("monthly music cap must remain at the low-cost launch limit")
        if self.max_drafts_per_month != 10:
            raise MusicFactoryError("monthly draft count must remain bounded")
        if self.max_final_generations_per_month != 3:
            raise MusicFactoryError("monthly final count must remain bounded")

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "default_tier": self.default_tier,
            "max_attempts": self.max_attempts,
            "draft_first_required": self.draft_first_required,
            "full_song_requires_approval": self.full_song_requires_approval,
            "automatic_retry": self.automatic_retry,
            "default_user_request_cap_usd": self.default_user_request_cap_usd,
            "final_user_request_cap_usd": self.final_user_request_cap_usd,
            "monthly_user_cap_usd": self.monthly_user_cap_usd,
            "max_drafts_per_month": self.max_drafts_per_month,
            "max_final_generations_per_month": self.max_final_generations_per_month,
        }

    def route(self, request: MusicRequest) -> LyriaCostRoute:
        route = LYRIA_COST_ROUTES[request.tier]
        expected_cap = (
            self.default_user_request_cap_usd
            if request.tier == "draft"
            else self.final_user_request_cap_usd
        )
        if route.fixed_cost_usd != expected_cap:
            raise MusicFactoryError("music route cost does not match user cap")
        return route


LOW_COST_MUSIC_POLICY: Final[MusicCostPolicy] = MusicCostPolicy()


@dataclass(frozen=True, slots=True)
class MusicPlan:
    request: MusicRequest
    route: LyriaCostRoute
    cost_policy: MusicCostPolicy
    estimated_cost_usd: float
    max_cost_usd: float
    plan_status: str
    render_status: str
    external_gates: tuple[str, ...]
    checksum: str

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36G.music-plan.v1",
            "checksum": self.checksum,
            "plan_status": self.plan_status,
            "render_status": self.render_status,
            "provider": "replicate",
            "model": self.route.model,
            "tier": self.route.tier,
            "preview_model": True,
            "fixed_cost_usd": self.route.fixed_cost_usd,
            "estimated_cost_usd": self.estimated_cost_usd,
            "max_cost_usd": self.max_cost_usd,
            "default_low_cost_route": self.route.tier == "draft",
            "cost_policy": self.cost_policy.public_snapshot(),
            "final_generation_approved": self.request.final_generation_approved,
            "final_approval_evidence_sha256": self.request.final_approval_evidence_sha256,
            "prior_draft_checksum_present": self.request.prior_draft_checksum is not None,
            "max_attempts": 1,
            "automatic_retry": False,
            "output_profile_id": self.request.output_profile_id,
            "provider_output": {
                "media_type": self.route.provider_output_media_type,
                "sample_rate_hz": self.route.provider_sample_rate_hz,
                "channels": self.route.provider_channels,
                "nominal_duration_seconds": self.route.nominal_duration_seconds,
            },
            "content": {
                "title": self.request.title,
                "language": self.request.language,
                "instrumental_only": self.request.instrumental_only,
                "prompt_sha256": _sha256_text(self.request.prompt),
                "prompt_characters": len(self.request.prompt),
                "lyrics_sha256": (
                    _sha256_text(self.request.lyrics) if self.request.lyrics else None
                ),
                "lyrics_characters": len(self.request.lyrics),
                "raw_prompt_returned": False,
                "raw_lyrics_returned": False,
            },
            "rights": self.request.rights.public_snapshot(),
            "external_gates": list(self.external_gates),
            "music_generation_requests": 0,
            "provider_spend_usd": 0.0,
        }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_music_plan(
    request: MusicRequest,
    *,
    policy: MusicCostPolicy = LOW_COST_MUSIC_POLICY,
) -> MusicPlan:
    route = policy.route(request)
    canonical = {
        "request": asdict(request),
        "route": asdict(route),
        "policy": asdict(policy),
        "external_gates": (
            "valid-replicate-credential",
            "lyria-preview-runtime-evidence",
            "music-rights-and-synthid-disclosure",
        ),
    }
    checksum = _sha256_text(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )
    return MusicPlan(
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
