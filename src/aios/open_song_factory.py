from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, Literal

SongRightsBasis = Literal["original", "licensed", "public-domain"]
SongRuntimeRouteId = Literal[
    "runpod-flex-a40",
    "ace-step-official-space-acceptance",
]

ACE_STEP_SOURCE_REPOSITORY: Final[str] = "ACE-Step/ACE-Step-1.5"
ACE_STEP_SOURCE_COMMIT: Final[str] = (
    "dce621408bee8c31b4fcf4811682eb9359e1bc94"
)
ACE_STEP_SOURCE_LICENSE: Final[str] = "MIT"
ACE_STEP_SOURCE_LICENSE_SHA256: Final[str] = (
    "05a6bce42a62636d2cfb24139cc008b6b899754e244175814bb5dd2f4a485357"
)
ACE_STEP_IMAGE_REPOSITORY: Final[str] = "ghcr.io/ace-step/ace-step-1.5"
ACE_STEP_IMAGE_INDEX_DIGEST: Final[str] = (
    "sha256:95652cd780c78a1b1a7f6f0335530430f0ae53d96c7c12d59f9f39fa23d38567"
)
ACE_STEP_IMAGE_AMD64_DIGEST: Final[str] = (
    "sha256:c289cb5c0cbc60d428baa9283a49966d2fe54ecf2028fa254f99f164f3953159"
)
ACE_STEP_MODEL_REPOSITORY: Final[str] = "ACE-Step/acestep-v15-base"
ACE_STEP_MODEL_REVISION: Final[str] = (
    "e432212fec32b8965a14ffa57ae653438d6abd14"
)
ACE_STEP_TURBO_MODEL_REPOSITORY: Final[str] = "ACE-Step/Ace-Step1.5"
ACE_STEP_TURBO_MODEL_REVISION: Final[str] = (
    "19671f406d603126926c1b7e2adc169acbcade22"
)
ACE_STEP_LANGUAGE_MODEL: Final[str] = "acestep-5Hz-lm-4B"
ACE_STEP_LANGUAGE_MODEL_REPOSITORY: Final[str] = (
    "ACE-Step/acestep-5Hz-lm-4B"
)
ACE_STEP_LANGUAGE_MODEL_REVISION: Final[str] = (
    "0a3ec94b557aea7d508da38b31cfe7341f6ff737"
)
ACE_STEP_SPACE_REPOSITORY: Final[str] = "ACE-Step/Ace-Step-v1.5"
ACE_STEP_SPACE_REVISION: Final[str] = (
    "7403460e9b34972f760317b56048f6cb9d4a3a11"
)
DEMUCS_SOURCE_REPOSITORY: Final[str] = "facebookresearch/demucs"
DEMUCS_SOURCE_COMMIT: Final[str] = (
    "ef66d254cd6d558e207eeff2c4b8d053db2e77dd"
)
DEMUCS_SOURCE_LICENSE: Final[str] = "MIT"
DEMUCS_SOURCE_LICENSE_SHA256: Final[str] = (
    "cf9b17822d1fcd4ff32ccbe14183386fb3adf6f2ff92dc184130823f7fc28173"
)
DEMUCS_MODEL: Final[str] = "htdemucs"
DEMUCS_CHECKPOINT_FILENAME: Final[str] = "955717e8-8726e21a.th"
DEMUCS_CHECKPOINT_SHA256: Final[str] = (
    "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4"
)
DEMUCS_CHECKPOINT_SIZE_BYTES: Final[int] = 84_141_911

RUNPOD_FLEX_RATE_USD_PER_SECOND: Final[float] = 0.00034
RUNPOD_OPERATOR_CAP_USD: Final[float] = 0.20
RUNPOD_MAX_BILLED_SECONDS: Final[int] = 588
OPEN_SONG_MONTHLY_USER_CAP_USD: Final[float] = 0.40
OPEN_SONG_MAX_ATTEMPTS: Final[int] = 1
OPEN_SONG_STEMS: Final[tuple[str, ...]] = (
    "vocals",
    "drums",
    "bass",
    "other",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
_KEY_RE = re.compile(r"^[A-G](?:#|b)?(?:m|maj|min)?$")
_FORBIDDEN_IMITATION_RE = re.compile(
    r"\b(?:in\s+the\s+style\s+of|sound\s+like|sounds\s+like|"
    r"voice\s+of|sing\s+like|imitat(?:e|ing|ion)|clone\s+(?:the\s+)?voice)\b",
    re.IGNORECASE,
)


class OpenSongFactoryError(ValueError):
    """An open-song plan cannot be created truthfully and safely."""


def _normalized_text(value: str, *, label: str, minimum: int, maximum: int) -> str:
    text = "\n".join(line.rstrip() for line in value.strip().splitlines()).strip()
    if not minimum <= len(text) <= maximum:
        raise OpenSongFactoryError(
            f"{label} must contain between {minimum} and {maximum} characters"
        )
    return text


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _checksum(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class OpenSongRightsEvidence:
    basis: SongRightsBasis
    commercial_use_authorized: bool
    provider_terms_accepted: bool
    ai_generated_disclosure_accepted: bool
    evidence_sha256: str | None = None

    def __post_init__(self) -> None:
        if self.basis not in {"original", "licensed", "public-domain"}:
            raise OpenSongFactoryError("song rights basis is unsupported")
        if not self.commercial_use_authorized:
            raise OpenSongFactoryError("commercial song use is not authorized")
        if not self.provider_terms_accepted:
            raise OpenSongFactoryError("provider terms must be accepted")
        if not self.ai_generated_disclosure_accepted:
            raise OpenSongFactoryError("AI-generated disclosure must be accepted")
        evidence = (self.evidence_sha256 or "").strip().lower() or None
        if self.basis != "original" and evidence is None:
            raise OpenSongFactoryError(
                "licensed or public-domain lyrics require rights evidence"
            )
        if evidence is not None and not _SHA256_RE.fullmatch(evidence):
            raise OpenSongFactoryError("song rights evidence checksum is invalid")
        object.__setattr__(self, "evidence_sha256", evidence)

    def public_snapshot(self) -> dict[str, object]:
        return {
            "basis": self.basis,
            "commercial_use_authorized": self.commercial_use_authorized,
            "provider_terms_accepted": self.provider_terms_accepted,
            "ai_generated_disclosure_required": True,
            "evidence_present": self.evidence_sha256 is not None,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True, slots=True)
class OpenSongRequest:
    title: str
    concept: str
    lyrics: str
    language: str
    duration_seconds: int
    bpm: int
    musical_key: str
    rights: OpenSongRightsEvidence
    time_signature: int = 4
    seed: int = 0
    output_profile_id: str = "wav-pcm-48k-stereo"

    def __post_init__(self) -> None:
        title = _normalized_text(
            self.title, label="song title", minimum=3, maximum=160
        )
        concept = _normalized_text(
            self.concept, label="song concept", minimum=20, maximum=1_000
        )
        lyrics = _normalized_text(
            self.lyrics, label="song lyrics", minimum=40, maximum=8_000
        )
        language = self.language.strip()
        musical_key = self.musical_key.strip()
        if not _LANGUAGE_RE.fullmatch(language):
            raise OpenSongFactoryError("song language must be a supported BCP-47 tag")
        if not 15 <= self.duration_seconds <= 180:
            raise OpenSongFactoryError("song duration must be between 15 and 180 seconds")
        if not 40 <= self.bpm <= 220:
            raise OpenSongFactoryError("song BPM must be between 40 and 220")
        if not _KEY_RE.fullmatch(musical_key):
            raise OpenSongFactoryError("song musical key is invalid")
        if self.time_signature not in {2, 3, 4, 6}:
            raise OpenSongFactoryError("song time signature is unsupported")
        if not 0 <= self.seed <= 2_147_483_647:
            raise OpenSongFactoryError("song seed is outside the supported range")
        if self.output_profile_id != "wav-pcm-48k-stereo":
            raise OpenSongFactoryError("open-song output profile is unsupported")
        imitation_text = f"{title}\n{concept}"
        if _FORBIDDEN_IMITATION_RE.search(imitation_text):
            raise OpenSongFactoryError("named-person or artist imitation is prohibited")
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "concept", concept)
        object.__setattr__(self, "lyrics", lyrics)
        object.__setattr__(self, "language", language)
        object.__setattr__(self, "musical_key", musical_key)


@dataclass(frozen=True, slots=True)
class OpenSongRuntimeRoute:
    route_id: SongRuntimeRouteId
    provider: str
    runtime_mode: str
    model: str
    model_revision: str
    language_model: str
    language_model_revision: str
    source_commit: str
    container_image_repository: str | None
    container_image_index_digest: str | None
    container_image_digest: str | None
    billing_basis: str
    rate_usd_per_second: float
    max_billed_seconds: int
    max_cost_usd: float
    requires_positive_provider_balance: bool
    acceptance_only: bool
    max_attempts: int = OPEN_SONG_MAX_ATTEMPTS

    def __post_init__(self) -> None:
        if self.max_attempts != 1:
            raise OpenSongFactoryError("open-song runtime permits exactly one attempt")
        if self.rate_usd_per_second < 0 or self.max_cost_usd < 0:
            raise OpenSongFactoryError("open-song runtime cost cannot be negative")
        if self.rate_usd_per_second * self.max_billed_seconds > self.max_cost_usd + 1e-9:
            raise OpenSongFactoryError("open-song runtime cap is below its billed-time bound")
        for label, digest in (
            ("container image index", self.container_image_index_digest),
            ("container image", self.container_image_digest),
        ):
            if digest is not None and not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise OpenSongFactoryError(f"open-song {label} digest is invalid")
        if (self.container_image_repository is None) != (self.container_image_digest is None):
            raise OpenSongFactoryError("open-song image repository and digest must be bound together")
        if self.container_image_digest is None and self.container_image_index_digest is not None:
            raise OpenSongFactoryError("open-song image index cannot exist without an image digest")
        if not re.fullmatch(r"[0-9a-f]{40}", self.model_revision):
            raise OpenSongFactoryError("open-song model revision is invalid")
        if not re.fullmatch(r"[0-9a-f]{40}", self.language_model_revision):
            raise OpenSongFactoryError("open-song language model revision is invalid")
        if not re.fullmatch(r"[0-9a-f]{40}", self.source_commit):
            raise OpenSongFactoryError("open-song source revision is invalid")

    def public_snapshot(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "provider": self.provider,
            "runtime_mode": self.runtime_mode,
            "model": self.model,
            "model_revision": self.model_revision,
            "language_model": self.language_model,
            "language_model_revision": self.language_model_revision,
            "source_commit": self.source_commit,
            "container_image_repository": self.container_image_repository,
            "container_image_index_digest": self.container_image_index_digest,
            "container_image_digest": self.container_image_digest,
            "container_image_role": (
                "audited-base" if self.route_id == "runpod-flex-a40" else None
            ),
            "runtime_handler_image_binding_required": (
                self.route_id == "runpod-flex-a40"
            ),
            "billing_basis": self.billing_basis,
            "rate_usd_per_second": self.rate_usd_per_second,
            "max_billed_seconds": self.max_billed_seconds,
            "max_cost_usd": self.max_cost_usd,
            "requires_positive_provider_balance": self.requires_positive_provider_balance,
            "acceptance_only": self.acceptance_only,
            "max_attempts": self.max_attempts,
            "automatic_retry": False,
            "automatic_cross_provider_fallback": False,
        }


RUNPOD_FLEX_A40_ROUTE: Final[OpenSongRuntimeRoute] = OpenSongRuntimeRoute(
    route_id="runpod-flex-a40",
    provider="runpod",
    runtime_mode="dedicated-serverless-gpu",
    model="acestep-v15-base",
    model_revision=ACE_STEP_MODEL_REVISION,
    language_model=ACE_STEP_LANGUAGE_MODEL,
    language_model_revision=ACE_STEP_LANGUAGE_MODEL_REVISION,
    source_commit=ACE_STEP_SOURCE_COMMIT,
    container_image_repository=ACE_STEP_IMAGE_REPOSITORY,
    container_image_index_digest=ACE_STEP_IMAGE_INDEX_DIGEST,
    container_image_digest=ACE_STEP_IMAGE_AMD64_DIGEST,
    billing_basis="gpu-seconds",
    rate_usd_per_second=RUNPOD_FLEX_RATE_USD_PER_SECOND,
    max_billed_seconds=RUNPOD_MAX_BILLED_SECONDS,
    max_cost_usd=RUNPOD_OPERATOR_CAP_USD,
    requires_positive_provider_balance=True,
    acceptance_only=False,
)

ACE_STEP_OFFICIAL_SPACE_ACCEPTANCE_ROUTE: Final[OpenSongRuntimeRoute] = (
    OpenSongRuntimeRoute(
        route_id="ace-step-official-space-acceptance",
        provider="huggingface-space",
        runtime_mode="official-shared-zerogpu-acceptance",
        model="acestep-v15-turbo",
        model_revision=ACE_STEP_TURBO_MODEL_REVISION,
        language_model=ACE_STEP_LANGUAGE_MODEL,
        language_model_revision=ACE_STEP_LANGUAGE_MODEL_REVISION,
        source_commit=ACE_STEP_SPACE_REVISION,
        container_image_repository=None,
        container_image_index_digest=None,
        container_image_digest=None,
        billing_basis="shared-zerogpu-quota",
        rate_usd_per_second=0.0,
        max_billed_seconds=0,
        max_cost_usd=0.0,
        requires_positive_provider_balance=False,
        acceptance_only=True,
    )
)

OPEN_SONG_RUNTIME_ROUTES: Final[dict[SongRuntimeRouteId, OpenSongRuntimeRoute]] = {
    RUNPOD_FLEX_A40_ROUTE.route_id: RUNPOD_FLEX_A40_ROUTE,
    ACE_STEP_OFFICIAL_SPACE_ACCEPTANCE_ROUTE.route_id: ACE_STEP_OFFICIAL_SPACE_ACCEPTANCE_ROUTE,
}


@dataclass(frozen=True, slots=True)
class OpenSongRuntimeBinding:
    """Owner-approved execution image and endpoint evidence for RunPod.

    The pinned ACE-Step image above is the audited *base* image.  Production
    execution requires a distinct AIONEX handler image derived from that base,
    with its own immutable digest, SBOM and source evidence.  Endpoint identity
    is represented only by a SHA-256 digest; the secret endpoint ID remains in
    the worker secret file.
    """

    route_id: SongRuntimeRouteId
    endpoint_id_sha256: str
    container_image_repository: str
    container_image_index_digest: str
    container_image_digest: str
    image_sbom_sha256: str
    handler_source_sha256: str

    def __post_init__(self) -> None:
        if self.route_id != "runpod-flex-a40":
            raise OpenSongFactoryError(
                "runtime binding is supported only for the RunPod route"
            )
        for label, value in (
            ("endpoint ID", self.endpoint_id_sha256),
            ("image SBOM", self.image_sbom_sha256),
            ("handler source", self.handler_source_sha256),
        ):
            normalized = value.strip().lower()
            if not _SHA256_RE.fullmatch(normalized):
                raise OpenSongFactoryError(
                    f"open-song {label} checksum is invalid"
                )
            object.__setattr__(
                self,
                {
                    "endpoint ID": "endpoint_id_sha256",
                    "image SBOM": "image_sbom_sha256",
                    "handler source": "handler_source_sha256",
                }[label],
                normalized,
            )
        repository = self.container_image_repository.strip().lower()
        if (
            not 5 <= len(repository) <= 240
            or " " in repository
            or "@" in repository
            or repository.startswith(("http://", "https://"))
        ):
            raise OpenSongFactoryError(
                "open-song runtime image repository is invalid"
            )
        object.__setattr__(self, "container_image_repository", repository)
        for field_name, label in (
            ("container_image_index_digest", "runtime image index"),
            ("container_image_digest", "runtime image"),
        ):
            digest = str(getattr(self, field_name)).strip().lower()
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise OpenSongFactoryError(
                    f"open-song {label} digest is invalid"
                )
            object.__setattr__(self, field_name, digest)
        if self.container_image_digest == ACE_STEP_IMAGE_AMD64_DIGEST:
            raise OpenSongFactoryError(
                "the ACE-Step base image cannot be claimed as the AIONEX handler image"
            )

    def public_snapshot(self) -> dict[str, object]:
        return {
            "route_id": self.route_id,
            "endpoint_id_sha256": self.endpoint_id_sha256,
            "container_image_repository": self.container_image_repository,
            "container_image_index_digest": self.container_image_index_digest,
            "container_image_digest": self.container_image_digest,
            "image_sbom_sha256": self.image_sbom_sha256,
            "handler_source_sha256": self.handler_source_sha256,
            "endpoint_id_returned": False,
            "runtime_image_verified": True,
        }


@dataclass(frozen=True, slots=True)
class OpenSongTask:
    task_id: str
    operation: str
    dependencies: tuple[str, ...]
    engine: str
    evidence_outputs: tuple[str, ...]

    def public_snapshot(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "operation": self.operation,
            "dependencies": list(self.dependencies),
            "engine": self.engine,
            "evidence_outputs": list(self.evidence_outputs),
        }


@dataclass(frozen=True, slots=True)
class OpenSongPlan:
    schema: str
    request: OpenSongRequest
    route: OpenSongRuntimeRoute
    tasks: tuple[OpenSongTask, ...]
    stems: tuple[str, ...]
    checksum: str

    def public_snapshot(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "title_sha256": _sha256(self.request.title),
            "title_characters": len(self.request.title),
            "concept_sha256": _sha256(self.request.concept),
            "concept_characters": len(self.request.concept),
            "lyrics_sha256": _sha256(self.request.lyrics),
            "lyrics_characters": len(self.request.lyrics),
            "language": self.request.language,
            "duration_seconds": self.request.duration_seconds,
            "bpm": self.request.bpm,
            "musical_key": self.request.musical_key,
            "time_signature": self.request.time_signature,
            "output_profile_id": self.request.output_profile_id,
            "rights": self.request.rights.public_snapshot(),
            "route": self.route.public_snapshot(),
            "stems": list(self.stems),
            "tasks": [task.public_snapshot() for task in self.tasks],
            "checksum": self.checksum,
            "private_title_returned": False,
            "private_concept_returned": False,
            "private_lyrics_returned": False,
            "known_person_voice": False,
            "voice_clone": False,
            "voice_transformation": False,
            "generated_vocals": True,
            "stems_required": True,
            "ai_generated_disclosure_required": True,
        }


def build_open_song_plan(
    request: OpenSongRequest,
    *,
    route_id: SongRuntimeRouteId = "runpod-flex-a40",
) -> OpenSongPlan:
    try:
        route = OPEN_SONG_RUNTIME_ROUTES[route_id]
    except KeyError as exc:
        raise OpenSongFactoryError("open-song runtime route is unsupported") from exc
    tasks = (
        OpenSongTask(
            task_id="lyrics",
            operation="governed-lyrics",
            dependencies=(),
            engine="local-contract",
            evidence_outputs=("lyrics_sha256", "lyrics_characters", "rights_evidence"),
        ),
        OpenSongTask(
            task_id="composition-vocals",
            operation="text-to-song-with-vocals",
            dependencies=("lyrics",),
            engine="ace-step-v1.5-base",
            evidence_outputs=(
                "full_song_sha256",
                "duration_seconds",
                "sample_rate_hz",
                "channels",
            ),
        ),
        OpenSongTask(
            task_id="stems",
            operation="four-stem-separation",
            dependencies=("composition-vocals",),
            engine="demucs-htdemucs",
            evidence_outputs=tuple(f"{stem}_sha256" for stem in OPEN_SONG_STEMS),
        ),
        OpenSongTask(
            task_id="mix",
            operation="audio-mix",
            dependencies=("stems",),
            engine="ffmpeg-9",
            evidence_outputs=("mix_sha256",),
        ),
        OpenSongTask(
            task_id="master",
            operation="audio-master",
            dependencies=("mix",),
            engine="ffmpeg-9",
            evidence_outputs=("master_sha256", "audio_qa"),
        ),
        OpenSongTask(
            task_id="waveform",
            operation="audio-waveform",
            dependencies=("master",),
            engine="ffmpeg-9",
            evidence_outputs=("waveform_sha256",),
        ),
        OpenSongTask(
            task_id="export",
            operation="governed-audio-export",
            dependencies=("master", "waveform"),
            engine="ffmpeg-9",
            evidence_outputs=("final_sha256", "studio_revision"),
        ),
    )
    checksum_payload = {
        "schema": "36G.open-song-plan.v1",
        "title_sha256": _sha256(request.title),
        "concept_sha256": _sha256(request.concept),
        "lyrics_sha256": _sha256(request.lyrics),
        "language": request.language,
        "duration_seconds": request.duration_seconds,
        "bpm": request.bpm,
        "musical_key": request.musical_key,
        "time_signature": request.time_signature,
        "seed": request.seed,
        "output_profile_id": request.output_profile_id,
        "rights": request.rights.public_snapshot(),
        "route": route.public_snapshot(),
        "stems": OPEN_SONG_STEMS,
        "tasks": [task.public_snapshot() for task in tasks],
        "ace_step": {
            "source_repository": ACE_STEP_SOURCE_REPOSITORY,
            "source_commit": ACE_STEP_SOURCE_COMMIT,
            "source_license": ACE_STEP_SOURCE_LICENSE,
            "source_license_sha256": ACE_STEP_SOURCE_LICENSE_SHA256,
            "image_repository": ACE_STEP_IMAGE_REPOSITORY,
            "image_index_digest": ACE_STEP_IMAGE_INDEX_DIGEST,
            "image_amd64_digest": ACE_STEP_IMAGE_AMD64_DIGEST,
            "model_repository": ACE_STEP_MODEL_REPOSITORY,
            "model_revision": ACE_STEP_MODEL_REVISION,
            "space_acceptance_model_repository": ACE_STEP_TURBO_MODEL_REPOSITORY,
            "space_acceptance_model_revision": ACE_STEP_TURBO_MODEL_REVISION,
            "language_model": ACE_STEP_LANGUAGE_MODEL,
            "language_model_repository": ACE_STEP_LANGUAGE_MODEL_REPOSITORY,
            "language_model_revision": ACE_STEP_LANGUAGE_MODEL_REVISION,
        },
        "demucs": {
            "source_repository": DEMUCS_SOURCE_REPOSITORY,
            "source_commit": DEMUCS_SOURCE_COMMIT,
            "source_license": DEMUCS_SOURCE_LICENSE,
            "source_license_sha256": DEMUCS_SOURCE_LICENSE_SHA256,
            "model": DEMUCS_MODEL,
            "checkpoint_filename": DEMUCS_CHECKPOINT_FILENAME,
            "checkpoint_sha256": DEMUCS_CHECKPOINT_SHA256,
            "checkpoint_size_bytes": DEMUCS_CHECKPOINT_SIZE_BYTES,
        },
    }
    return OpenSongPlan(
        schema="36G.open-song-plan.v1",
        request=request,
        route=route,
        tasks=tasks,
        stems=OPEN_SONG_STEMS,
        checksum=_checksum(checksum_payload),
    )
