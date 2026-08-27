"""Durable Phase 36G open-song execution authority.

The authority is deliberately separate from the fixed-output Lyria/Stability music
rows. It owns a single ACE-Step full-song job, a four-stem manifest, provider job
reconciliation, GPU-second cost accounting, and final Media DAG/Studio evidence.
It never stores raw title, concept, lyrics, credentials, or signed URLs in public
snapshots.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Iterable, TypedDict
from uuid import uuid4

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aios.open_song_factory import (
    ACE_STEP_IMAGE_AMD64_DIGEST,
    ACE_STEP_IMAGE_INDEX_DIGEST,
    ACE_STEP_IMAGE_REPOSITORY,
)
from app.db.models import (
    AudioSongExecution,
    AuditEvent,
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    StudioAsset,
)

_SHA256_HEX = frozenset("0123456789abcdef")
_REQUIRED_STEMS = ("vocals", "drums", "bass", "other")
_TERMINAL = frozenset({"completed", "failed", "needs_review"})
_ACTIVE = frozenset({"queued", "running", "rendering"})
_PROVIDER_ACTIVE = frozenset({"not_started", "submitting", "submitted", "running"})


class AudioSongExecutionError(ValueError):
    """A durable open-song transition is invalid or unsafe."""


class _StoredAudioArtifact(TypedDict):
    storage_backend: str
    storage_key: str
    checksum: str
    size_bytes: int
    media_type: str
    duration_seconds: float
    sample_rate_hz: int
    channels: int


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash(value: str, *, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in _SHA256_HEX for char in normalized):
        raise AudioSongExecutionError(f"{label} checksum is invalid")
    return normalized


def _revision(value: str, *, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 40 or any(char not in _SHA256_HEX for char in normalized):
        raise AudioSongExecutionError(f"{label} revision is invalid")
    return normalized


def _image_digest(value: str | None, *, label: str) -> str | None:
    normalized = str(value or "").strip().lower() or None
    if normalized is None:
        return None
    if not normalized.startswith("sha256:"):
        raise AudioSongExecutionError(f"{label} digest is invalid")
    _hash(normalized.removeprefix("sha256:"), label=label)
    return normalized


def _required(value: Any, *, label: str, maximum: int = 900) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise AudioSongExecutionError(f"{label} is invalid")
    return text


def _positive_int(value: Any, *, label: str, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AudioSongExecutionError(f"{label} is invalid") from exc
    if parsed <= 0 or parsed > maximum:
        raise AudioSongExecutionError(f"{label} is invalid")
    return parsed


def _non_negative_float(value: Any, *, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise AudioSongExecutionError(f"{label} is invalid") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise AudioSongExecutionError(f"{label} is invalid")
    return parsed


def _cost(value: Any, *, label: str) -> float:
    parsed = _non_negative_float(value, label=label)
    return round(parsed + 0.0, 6)


def _stem_manifest(value: dict[str, Any]) -> dict[str, _StoredAudioArtifact]:
    if set(value) != set(_REQUIRED_STEMS):
        raise AudioSongExecutionError("open-song stem manifest is incomplete")
    result: dict[str, _StoredAudioArtifact] = {}
    for stem in _REQUIRED_STEMS:
        item = value.get(stem)
        if not isinstance(item, dict):
            raise AudioSongExecutionError("open-song stem manifest entry is invalid")
        duration = _non_negative_float(item.get("duration_seconds"), label="stem duration")
        sample_rate = _positive_int(
            item.get("sample_rate_hz"), label="stem sample rate", maximum=384_000
        )
        channels = _positive_int(item.get("channels"), label="stem channels", maximum=8)
        result[stem] = {
            "storage_backend": _required(
                item.get("storage_backend"), label="stem storage backend", maximum=40
            ),
            "storage_key": _required(item.get("storage_key"), label="stem storage key"),
            "checksum": _hash(str(item.get("checksum") or ""), label="stem"),
            "size_bytes": _positive_int(
                item.get("size_bytes"), label="stem size", maximum=2_147_483_647
            ),
            "media_type": _required(
                item.get("media_type"), label="stem media type", maximum=100
            ),
            "duration_seconds": duration,
            "sample_rate_hz": sample_rate,
            "channels": channels,
        }
    return result


def _safe_provider_metadata(value: dict[str, Any] | None) -> dict[str, Any]:
    if not value:
        return {}
    safe: dict[str, Any] = {}
    for key, item in value.items():
        normalized = str(key).strip().lower()
        if normalized in {
            "credential",
            "authorization",
            "api_key",
            "token",
            "prompt",
            "lyrics",
            "title",
            "concept",
            "signed_url",
            "storage_key",
            "provider_job_id",
            "output_url",
        }:
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            safe[normalized[:80]] = item if not isinstance(item, str) else item[:240]
        elif isinstance(item, list):
            bounded = [
                entry if not isinstance(entry, str) else entry[:120]
                for entry in item[:24]
                if isinstance(entry, (str, int, float, bool)) or entry is None
            ]
            safe[normalized[:80]] = bounded
        elif isinstance(item, dict):
            nested = _safe_provider_metadata(item)
            if nested:
                safe[normalized[:80]] = nested
    return safe


@dataclass(frozen=True, slots=True)
class AudioSongExecutionSpec:
    organization_id: str
    requested_by_id: str
    graph_id: str
    target_node_id: str
    route_id: str
    provider: str
    model: str
    model_revision: str
    language_model: str
    language_model_revision: str
    source_commit: str
    base_container_image_repository: str | None
    base_container_image_index_digest: str | None
    base_container_image_digest: str | None
    endpoint_id_sha256: str | None
    image_sbom_sha256: str | None
    handler_source_sha256: str | None
    container_image_repository: str | None
    container_image_index_digest: str | None
    container_image_digest: str | None
    separation_model: str
    separation_revision: str
    separation_source_commit: str
    separation_checkpoint_sha256: str
    idempotency_key: str
    plan_checksum: str
    runtime_evidence_sha256: str
    pricing_evidence_sha256: str
    license_evidence_sha256: str
    title_sha256: str
    title_characters: int
    concept_sha256: str
    concept_characters: int
    lyrics_sha256: str
    lyrics_characters: int
    language: str
    duration_seconds: int
    bpm: int
    musical_key: str
    time_signature: int
    seed: int
    output_profile_id: str
    rights_basis: str
    rights_evidence_sha256: str | None
    commercial_use_authorized: bool
    provider_terms_accepted: bool
    ai_generated_disclosure_required: bool
    estimated_cost_usd: float
    max_cost_usd: float
    cost_basis: str
    rate_usd_per_second: float
    max_billed_seconds: int
    workspace_id: str | None = None
    project_id: str | None = None
    studio_job_id: str | None = None
    studio_asset_id: str | None = None
    max_attempts: int = 1

    def normalized(self) -> dict[str, Any]:
        if self.max_attempts != 1:
            raise AudioSongExecutionError("open-song max_attempts must equal one")
        if not self.commercial_use_authorized or not self.provider_terms_accepted:
            raise AudioSongExecutionError("open-song rights or provider terms are missing")
        if not self.ai_generated_disclosure_required:
            raise AudioSongExecutionError("open-song AI disclosure is mandatory")
        duration = _positive_int(
            self.duration_seconds, label="song duration", maximum=180
        )
        bpm = _positive_int(self.bpm, label="song BPM", maximum=220)
        time_signature = _positive_int(
            self.time_signature, label="song time signature", maximum=12
        )
        title_chars = _positive_int(
            self.title_characters, label="song title characters", maximum=160
        )
        concept_chars = _positive_int(
            self.concept_characters, label="song concept characters", maximum=1_000
        )
        lyrics_chars = _positive_int(
            self.lyrics_characters, label="song lyrics characters", maximum=8_000
        )
        max_cost = _cost(self.max_cost_usd, label="song max cost")
        estimated = _cost(self.estimated_cost_usd, label="song estimated cost")
        if estimated > max_cost:
            raise AudioSongExecutionError("song estimated cost exceeds its maximum")
        rate = _non_negative_float(
            self.rate_usd_per_second, label="song GPU rate"
        )
        max_seconds = int(self.max_billed_seconds)
        if max_seconds < 0 or max_seconds > 86_400:
            raise AudioSongExecutionError("song billed-time bound is invalid")
        if round(rate * max_seconds, 6) > max_cost + 1e-9:
            raise AudioSongExecutionError("song billed-time bound exceeds its cap")
        route_id = _required(self.route_id, label="song route", maximum=80)
        provider = _required(self.provider, label="song provider", maximum=40)
        base_image_repository = (
            str(self.base_container_image_repository or "").strip().lower() or None
        )
        base_image_index_digest = _image_digest(
            self.base_container_image_index_digest, label="song base image index"
        )
        base_image_digest = _image_digest(
            self.base_container_image_digest, label="song base image"
        )
        endpoint_hash = (
            _hash(self.endpoint_id_sha256, label="song endpoint ID")
            if self.endpoint_id_sha256
            else None
        )
        image_sbom_hash = (
            _hash(self.image_sbom_sha256, label="song image SBOM")
            if self.image_sbom_sha256
            else None
        )
        handler_source_hash = (
            _hash(self.handler_source_sha256, label="song handler source")
            if self.handler_source_sha256
            else None
        )
        image_repository = str(self.container_image_repository or "").strip().lower() or None
        image_index_digest = _image_digest(
            self.container_image_index_digest, label="song image index"
        )
        image_digest = _image_digest(
            self.container_image_digest, label="song image"
        )
        if route_id == "runpod-flex-a40":
            if provider != "runpod":
                raise AudioSongExecutionError("RunPod route provider is invalid")
            if (
                base_image_repository != ACE_STEP_IMAGE_REPOSITORY
                or base_image_index_digest != ACE_STEP_IMAGE_INDEX_DIGEST
                or base_image_digest != ACE_STEP_IMAGE_AMD64_DIGEST
            ):
                raise AudioSongExecutionError(
                    "RunPod route base image evidence is invalid"
                )
            if not all(
                (
                    endpoint_hash,
                    image_sbom_hash,
                    handler_source_hash,
                    image_repository,
                    image_index_digest,
                    image_digest,
                )
            ):
                raise AudioSongExecutionError(
                    "RunPod route requires a bound handler image and endpoint evidence"
                )
            if image_digest == base_image_digest:
                raise AudioSongExecutionError(
                    "RunPod handler image cannot equal the ACE-Step base image"
                )
            if max_cost <= 0 or rate <= 0 or max_seconds <= 0:
                raise AudioSongExecutionError("RunPod route requires a positive GPU cost cap")
        elif route_id == "ace-step-official-space-acceptance":
            if provider != "huggingface-space":
                raise AudioSongExecutionError("acceptance route provider is invalid")
            if any(
                (
                    base_image_repository,
                    base_image_index_digest,
                    base_image_digest,
                    endpoint_hash,
                    image_sbom_hash,
                    handler_source_hash,
                    image_repository,
                    image_index_digest,
                    image_digest,
                )
            ):
                raise AudioSongExecutionError(
                    "acceptance route cannot claim an endpoint or container image"
                )
            if max_cost != 0.0 or estimated != 0.0 or rate != 0.0 or max_seconds != 0:
                raise AudioSongExecutionError("acceptance route cannot claim paid GPU cost")
        else:
            raise AudioSongExecutionError("open-song route is unsupported")
        rights_hash = (
            _hash(self.rights_evidence_sha256, label="song rights evidence")
            if self.rights_evidence_sha256
            else None
        )
        return {
            "organization_id": _required(
                self.organization_id, label="organization", maximum=36
            ),
            "requested_by_id": _required(
                self.requested_by_id, label="requester", maximum=36
            ),
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "studio_job_id": self.studio_job_id,
            "studio_asset_id": self.studio_asset_id,
            "graph_id": _required(self.graph_id, label="song graph", maximum=36),
            "target_node_id": _required(
                self.target_node_id, label="song target node", maximum=36
            ),
            "route_id": route_id,
            "provider": provider,
            "model": _required(self.model, label="song model", maximum=160),
            "model_revision": _revision(
                self.model_revision, label="song model"
            ),
            "language_model": _required(
                self.language_model, label="song language model", maximum=160
            ),
            "language_model_revision": _revision(
                self.language_model_revision, label="song language model"
            ),
            "source_commit": _revision(
                self.source_commit, label="song source"
            ),
            "base_container_image_repository": base_image_repository,
            "base_container_image_index_digest": base_image_index_digest,
            "base_container_image_digest": base_image_digest,
            "endpoint_id_sha256": endpoint_hash,
            "image_sbom_sha256": image_sbom_hash,
            "handler_source_sha256": handler_source_hash,
            "container_image_repository": image_repository,
            "container_image_index_digest": image_index_digest,
            "container_image_digest": image_digest,
            "separation_model": _required(
                self.separation_model, label="stem model", maximum=80
            ),
            "separation_revision": _required(
                self.separation_revision, label="stem revision", maximum=64
            ),
            "separation_source_commit": _revision(
                self.separation_source_commit, label="stem source"
            ),
            "separation_checkpoint_sha256": _hash(
                self.separation_checkpoint_sha256, label="stem checkpoint"
            ),
            "idempotency_key": _required(
                self.idempotency_key, label="song idempotency key", maximum=160
            ),
            "plan_checksum": _hash(self.plan_checksum, label="song plan"),
            "runtime_evidence_sha256": _hash(
                self.runtime_evidence_sha256, label="song runtime evidence"
            ),
            "pricing_evidence_sha256": _hash(
                self.pricing_evidence_sha256, label="song pricing evidence"
            ),
            "license_evidence_sha256": _hash(
                self.license_evidence_sha256, label="song license evidence"
            ),
            "title_sha256": _hash(self.title_sha256, label="song title"),
            "title_characters": title_chars,
            "concept_sha256": _hash(self.concept_sha256, label="song concept"),
            "concept_characters": concept_chars,
            "lyrics_sha256": _hash(self.lyrics_sha256, label="song lyrics"),
            "lyrics_characters": lyrics_chars,
            "language": _required(self.language, label="song language", maximum=24),
            "duration_seconds": duration,
            "bpm": bpm,
            "musical_key": _required(
                self.musical_key, label="song musical key", maximum=16
            ),
            "time_signature": time_signature,
            "seed": int(self.seed),
            "output_profile_id": _required(
                self.output_profile_id, label="song output profile", maximum=80
            ),
            "rights_basis": _required(
                self.rights_basis, label="song rights basis", maximum=32
            ),
            "rights_evidence_sha256": rights_hash,
            "commercial_use_authorized": True,
            "provider_terms_accepted": True,
            "ai_generated_disclosure_required": True,
            "estimated_cost_usd": estimated,
            "max_cost_usd": max_cost,
            "cost_basis": _required(
                self.cost_basis, label="song cost basis", maximum=80
            ),
            "rate_usd_per_second": rate,
            "max_billed_seconds": max_seconds,
            "max_attempts": 1,
        }


async def create_audio_song_execution(
    session: AsyncSession,
    *,
    spec: AudioSongExecutionSpec,
) -> AudioSongExecution:
    values = spec.normalized()
    existing = await session.scalar(
        select(AudioSongExecution)
        .where(
            AudioSongExecution.organization_id == values["organization_id"],
            AudioSongExecution.idempotency_key == values["idempotency_key"],
        )
        .with_for_update()
    )
    if existing is not None:
        immutable = {
            "plan_checksum": values["plan_checksum"],
            "graph_id": values["graph_id"],
            "target_node_id": values["target_node_id"],
            "route_id": values["route_id"],
            "provider": values["provider"],
            "model": values["model"],
            "model_revision": values["model_revision"],
            "language_model": values["language_model"],
            "language_model_revision": values["language_model_revision"],
            "source_commit": values["source_commit"],
            "base_container_image_repository": values[
                "base_container_image_repository"
            ],
            "base_container_image_index_digest": values[
                "base_container_image_index_digest"
            ],
            "base_container_image_digest": values[
                "base_container_image_digest"
            ],
            "endpoint_id_sha256": values["endpoint_id_sha256"],
            "image_sbom_sha256": values["image_sbom_sha256"],
            "handler_source_sha256": values["handler_source_sha256"],
            "container_image_repository": values["container_image_repository"],
            "container_image_index_digest": values["container_image_index_digest"],
            "container_image_digest": values["container_image_digest"],
            "separation_model": values["separation_model"],
            "separation_revision": values["separation_revision"],
            "separation_source_commit": values["separation_source_commit"],
            "separation_checkpoint_sha256": values["separation_checkpoint_sha256"],
            "max_cost_usd": values["max_cost_usd"],
        }
        if any(getattr(existing, key) != value for key, value in immutable.items()):
            raise AudioSongExecutionError(
                "open-song idempotency key conflicts with another plan"
            )
        return existing
    row = AudioSongExecution(
        **values,
        operation="generate-open-song",
        status="planned",
        provider_state="not_started",
        actual_cost_usd=None,
        actual_cost_known=False,
        attempts=0,
        polls=0,
        fencing_token=0,
        provider_metadata={},
        error_metadata={},
        stem_manifest={},
        stem_count=0,
        final_audio_qa={},
    )
    session.add(row)
    await session.flush()
    return row


def _month_bounds(current: datetime) -> tuple[datetime, datetime]:
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


async def _monthly_reserved_cost(
    session: AsyncSession,
    *,
    organization_id: str,
    requested_by_id: str,
    current: datetime,
    exclude_id: str,
) -> float:
    start, end = _month_bounds(current)
    rows = list(
        (
            await session.scalars(
                select(AudioSongExecution)
                .where(
                    AudioSongExecution.organization_id == organization_id,
                    AudioSongExecution.requested_by_id == requested_by_id,
                    AudioSongExecution.id != exclude_id,
                    AudioSongExecution.created_at >= start,
                    AudioSongExecution.created_at < end,
                    AudioSongExecution.status.in_(
                        ("queued", "running", "rendering", "completed", "needs_review")
                    ),
                )
                .order_by(AudioSongExecution.created_at, AudioSongExecution.id)
                .with_for_update()
            )
        ).all()
    )
    total = 0.0
    for item in rows:
        if item.status == "completed" and item.actual_cost_known:
            total += float(item.actual_cost_usd or 0.0)
        else:
            total += float(item.max_cost_usd or 0.0)
    return round(total, 6)


async def arm_audio_song_execution(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
    approved_max_cost_usd: float,
    monthly_user_cap_usd: float,
    provider_balance_usd: float | None,
    balance_evidence_sha256: str | None,
    current: datetime | None = None,
) -> AudioSongExecution:
    now = current or _now()
    row = await session.scalar(
        select(AudioSongExecution)
        .where(
            AudioSongExecution.id == execution_id,
            AudioSongExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    if row.status != "planned" or row.provider_state != "not_started":
        raise AudioSongExecutionError("open-song execution cannot be armed")
    approved = _cost(approved_max_cost_usd, label="approved song cost")
    if approved != round(float(row.max_cost_usd), 6):
        raise AudioSongExecutionError("approved song cost must match the durable cap")
    monthly_cap = _cost(monthly_user_cap_usd, label="monthly song cap")
    reserved = await _monthly_reserved_cost(
        session,
        organization_id=row.organization_id,
        requested_by_id=row.requested_by_id,
        current=now,
        exclude_id=row.id,
    )
    if round(reserved + approved, 6) > monthly_cap + 1e-9:
        raise AudioSongExecutionError("open-song monthly user cost cap is exceeded")
    metadata = dict(row.provider_metadata or {})
    if row.provider == "runpod":
        balance = _non_negative_float(
            provider_balance_usd, label="RunPod provider balance"
        )
        evidence = _hash(
            str(balance_evidence_sha256 or ""), label="RunPod balance evidence"
        )
        if balance + 1e-9 < approved:
            raise AudioSongExecutionError(
                "RunPod balance cannot fund the approved open-song cap"
            )
        metadata.update(
            {
                "balance_evidence_sha256": evidence,
                "provider_balance_sufficient_at_arm": True,
            }
        )
    else:
        if provider_balance_usd not in {None, 0, 0.0}:
            raise AudioSongExecutionError(
                "acceptance-only route must not receive a paid provider balance"
            )
    metadata.update(
        {
            "monthly_reserved_before_usd": reserved,
            "monthly_reserved_after_usd": round(reserved + approved, 6),
            "monthly_user_cap_usd": monthly_cap,
            "armed_at": now.isoformat(),
        }
    )
    row.provider_metadata = metadata
    row.status = "queued"
    row.available_at = None
    row.updated_at = now
    await session.flush()
    return row


def _claim_query(
    *,
    current: datetime,
    allowed_route_ids: frozenset[str] | None = None,
    endpoint_id_sha256: str | None = None,
) -> Select[tuple[AudioSongExecution]]:
    query = select(AudioSongExecution).where(
        AudioSongExecution.status == "queued",
        AudioSongExecution.provider_state.in_(
            ("not_started", "submitted", "running")
        ),
        or_(
            AudioSongExecution.available_at.is_(None),
            AudioSongExecution.available_at <= current,
        ),
    )
    if allowed_route_ids is not None:
        query = query.where(AudioSongExecution.route_id.in_(allowed_route_ids))
    if endpoint_id_sha256 is not None:
        query = query.where(
            AudioSongExecution.endpoint_id_sha256 == endpoint_id_sha256
        )
    return (
        query.order_by(AudioSongExecution.created_at, AudioSongExecution.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )


async def claim_audio_song_execution(
    session: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int,
    allowed_route_ids: Iterable[str] | None = None,
    endpoint_id_sha256: str | None = None,
    current: datetime | None = None,
) -> AudioSongExecution | None:
    now = current or _now()
    lease = _positive_int(lease_seconds, label="song lease", maximum=3_600)
    routes: frozenset[str] | None = None
    if allowed_route_ids is not None:
        routes = frozenset(
            _required(route_id, label="song worker route", maximum=80)
            for route_id in allowed_route_ids
        )
        if not routes:
            raise AudioSongExecutionError(
                "open-song worker route allowlist cannot be empty"
            )
    endpoint_hash = (
        _hash(endpoint_id_sha256, label="song endpoint")
        if endpoint_id_sha256 is not None
        else None
    )
    row = await session.scalar(
        _claim_query(
            current=now,
            allowed_route_ids=routes,
            endpoint_id_sha256=endpoint_hash,
        )
    )
    if row is None:
        return None
    if row.provider_state == "not_started" and row.attempts == 0:
        row.attempts = 1
    if row.attempts > row.max_attempts:
        row.status = "failed"
        row.provider_state = "failed"
        row.error_code = "max_attempts_exhausted"
        row.completed_at = now
        await session.flush()
        return None
    row.status = "running"
    row.fencing_token += 1
    row.lease_owner = _required(worker_id, label="song worker", maximum=160)
    row.lease_token = uuid4().hex
    row.lease_expires_at = now + timedelta(seconds=lease)
    row.available_at = None
    row.updated_at = now
    await session.flush()
    return row


def _verify_lease(
    row: AudioSongExecution,
    *,
    worker_id: str,
    lease_token: str,
    fencing_token: int,
    current: datetime,
) -> None:
    if row.status != "running":
        raise AudioSongExecutionError("open-song execution is not running")
    if row.lease_owner != worker_id or row.lease_token != lease_token:
        raise AudioSongExecutionError("open-song lease ownership changed")
    if row.fencing_token != fencing_token:
        raise AudioSongExecutionError("open-song fencing token is stale")
    if row.lease_expires_at is None or row.lease_expires_at <= current:
        raise AudioSongExecutionError("open-song lease expired")


async def renew_audio_song_lease(
    session: AsyncSession,
    *,
    execution_id: str,
    worker_id: str,
    lease_token: str,
    fencing_token: int,
    lease_seconds: int,
    current: datetime | None = None,
) -> AudioSongExecution:
    now = current or _now()
    row = await session.scalar(
        select(AudioSongExecution)
        .where(AudioSongExecution.id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    _verify_lease(
        row,
        worker_id=worker_id,
        lease_token=lease_token,
        fencing_token=fencing_token,
        current=now,
    )
    row.lease_expires_at = now + timedelta(
        seconds=_positive_int(lease_seconds, label="song lease", maximum=3_600)
    )
    row.updated_at = now
    await session.flush()
    return row


async def mark_audio_song_submitting(
    session: AsyncSession,
    *,
    execution_id: str,
    worker_id: str,
    lease_token: str,
    fencing_token: int,
    current: datetime | None = None,
) -> AudioSongExecution:
    now = current or _now()
    row = await session.scalar(
        select(AudioSongExecution)
        .where(AudioSongExecution.id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    _verify_lease(
        row,
        worker_id=worker_id,
        lease_token=lease_token,
        fencing_token=fencing_token,
        current=now,
    )
    if row.provider_state != "not_started" or row.provider_job_id:
        raise AudioSongExecutionError("open-song provider submission already crossed")
    row.provider_state = "submitting"
    row.provider_submitted_at = now
    row.updated_at = now
    await session.flush()
    return row


async def record_audio_song_provider_job(
    session: AsyncSession,
    *,
    execution_id: str,
    worker_id: str,
    lease_token: str,
    fencing_token: int,
    provider_job_id: str,
    provider_metadata: dict[str, Any] | None = None,
    current: datetime | None = None,
) -> AudioSongExecution:
    now = current or _now()
    row = await session.scalar(
        select(AudioSongExecution)
        .where(AudioSongExecution.id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    _verify_lease(
        row,
        worker_id=worker_id,
        lease_token=lease_token,
        fencing_token=fencing_token,
        current=now,
    )
    job_id = _required(provider_job_id, label="provider song job", maximum=240)
    if row.provider_job_id and row.provider_job_id != job_id:
        raise AudioSongExecutionError("open-song provider job identity changed")
    if row.provider_state not in {"submitting", "submitted", "running"}:
        raise AudioSongExecutionError("open-song provider job cannot be recorded")
    row.provider_job_id = job_id
    row.provider_job_id_sha256 = _sha256(job_id)
    row.provider_state = "submitted"
    row.provider_metadata = {
        **(row.provider_metadata or {}),
        **_safe_provider_metadata(provider_metadata),
        "provider_job_recorded": True,
    }
    row.updated_at = now
    await session.flush()
    return row


async def record_audio_song_provider_poll(
    session: AsyncSession,
    *,
    execution_id: str,
    worker_id: str,
    lease_token: str,
    fencing_token: int,
    state: str,
    provider_metadata: dict[str, Any] | None = None,
    current: datetime | None = None,
) -> AudioSongExecution:
    now = current or _now()
    row = await session.scalar(
        select(AudioSongExecution)
        .where(AudioSongExecution.id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    _verify_lease(
        row,
        worker_id=worker_id,
        lease_token=lease_token,
        fencing_token=fencing_token,
        current=now,
    )
    if not row.provider_job_id:
        raise AudioSongExecutionError("open-song provider job is not durable")
    normalized = state.strip().lower()
    if normalized not in {"submitted", "running"}:
        raise AudioSongExecutionError("open-song provider poll state is invalid")
    row.provider_state = normalized
    row.polls += 1
    row.provider_metadata = {
        **(row.provider_metadata or {}),
        **_safe_provider_metadata(provider_metadata),
    }
    row.updated_at = now
    await session.flush()
    return row


async def defer_audio_song_provider_poll(
    session: AsyncSession,
    *,
    execution_id: str,
    worker_id: str,
    lease_token: str,
    fencing_token: int,
    delay_seconds: int,
    current: datetime | None = None,
) -> AudioSongExecution:
    """Release a durable provider job for a bounded later poll."""

    now = current or _now()
    delay = _positive_int(delay_seconds, label="song poll delay", maximum=300)
    row = await session.scalar(
        select(AudioSongExecution)
        .where(AudioSongExecution.id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    _verify_lease(
        row,
        worker_id=worker_id,
        lease_token=lease_token,
        fencing_token=fencing_token,
        current=now,
    )
    if not row.provider_job_id or row.provider_state not in {"submitted", "running"}:
        raise AudioSongExecutionError(
            "open-song provider poll cannot be deferred without a durable job"
        )
    row.status = "queued"
    row.available_at = now + timedelta(seconds=delay)
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None
    row.updated_at = now
    await session.flush()
    return row


async def complete_audio_song_provider_output(
    session: AsyncSession,
    *,
    execution_id: str,
    worker_id: str,
    lease_token: str,
    fencing_token: int,
    full_song: dict[str, Any],
    stems: dict[str, Any],
    actual_billed_seconds: float | None,
    actual_cost_usd: float | None,
    provider_metadata: dict[str, Any] | None = None,
    current: datetime | None = None,
) -> AudioSongExecution:
    """Atomically publish one governed song bundle into the Media DAG."""

    now = current or _now()
    row = await session.scalar(
        select(AudioSongExecution)
        .where(AudioSongExecution.id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    _verify_lease(
        row,
        worker_id=worker_id,
        lease_token=lease_token,
        fencing_token=fencing_token,
        current=now,
    )
    if row.provider_state not in {"submitted", "running"}:
        raise AudioSongExecutionError("open-song provider output is not expected")
    if row.provider != "huggingface-space" and not row.provider_job_id:
        raise AudioSongExecutionError("open-song provider job ID is missing")

    manifest = _stem_manifest(stems)
    duration = _non_negative_float(
        full_song.get("duration_seconds"), label="full song duration"
    )
    song: _StoredAudioArtifact = {
        "storage_backend": _required(
            full_song.get("storage_backend"),
            label="full song storage backend",
            maximum=40,
        ),
        "storage_key": _required(
            full_song.get("storage_key"), label="full song storage key"
        ),
        "checksum": _hash(
            str(full_song.get("checksum") or ""), label="full song"
        ),
        "size_bytes": _positive_int(
            full_song.get("size_bytes"),
            label="full song size",
            maximum=2_147_483_647,
        ),
        "media_type": _required(
            full_song.get("media_type"), label="full song media type", maximum=100
        ),
        "duration_seconds": duration,
        "sample_rate_hz": _positive_int(
            full_song.get("sample_rate_hz"),
            label="full song sample rate",
            maximum=384_000,
        ),
        "channels": _positive_int(
            full_song.get("channels"), label="full song channels", maximum=8
        ),
    }
    if (
        song["media_type"] != "audio/wav"
        or song["sample_rate_hz"] != 48_000
        or song["channels"] != 2
    ):
        raise AudioSongExecutionError(
            "open-song full output must be 48 kHz stereo WAV"
        )
    if not 1.0 <= duration <= float(row.duration_seconds) + 10.0:
        raise AudioSongExecutionError("open-song full output duration is invalid")
    storage_keys = {song["storage_key"]}
    for stem, item in manifest.items():
        if (
            item["media_type"] != "audio/wav"
            or item["sample_rate_hz"] != 48_000
            or item["channels"] != 2
        ):
            raise AudioSongExecutionError(
                f"open-song {stem} stem must be 48 kHz stereo WAV"
            )
        if abs(float(item["duration_seconds"]) - duration) > 0.05:
            raise AudioSongExecutionError(
                "open-song stem durations must match the full song"
            )
        if item["storage_key"] in storage_keys:
            raise AudioSongExecutionError("open-song storage keys must be distinct")
        storage_keys.add(item["storage_key"])

    metadata = dict(provider_metadata or {})
    expected_metadata = {
        "schema": "aionex.open-song-provider-result.v1",
        "source_commit": row.source_commit,
        "model_revision": row.model_revision,
        "language_model_revision": row.language_model_revision,
        "separation_source_commit": row.separation_source_commit,
        "separation_checkpoint_sha256": row.separation_checkpoint_sha256,
    }
    for key, expected_value in expected_metadata.items():
        if metadata.get(key) != expected_value:
            raise AudioSongExecutionError(
                f"open-song provider evidence mismatch: {key}"
            )
    if row.provider == "runpod":
        if metadata.get("container_image_digest") != row.container_image_digest:
            raise AudioSongExecutionError(
                "open-song provider image evidence does not match the durable route"
            )
    elif metadata.get("container_image_digest") not in {None, ""}:
        raise AudioSongExecutionError(
            "acceptance-only route cannot claim a container image"
        )

    billed = (
        _non_negative_float(actual_billed_seconds, label="actual billed seconds")
        if actual_billed_seconds is not None
        else None
    )
    actual = (
        _cost(actual_cost_usd, label="actual song cost")
        if actual_cost_usd is not None
        else None
    )
    if row.provider == "runpod":
        if billed is None or actual is None:
            raise AudioSongExecutionError(
                "RunPod open-song completion requires actual GPU cost evidence"
            )
        if billed > float(row.max_billed_seconds) + 1e-9:
            raise AudioSongExecutionError("open-song billed time exceeds its cap")
        if actual > float(row.max_cost_usd) + 1e-9:
            raise AudioSongExecutionError("open-song actual cost exceeds its cap")
        expected_cost = round(float(row.rate_usd_per_second) * billed, 6)
        if abs(expected_cost - actual) > 0.000002:
            raise AudioSongExecutionError(
                "open-song GPU cost evidence is inconsistent"
            )
    elif actual not in {None, 0.0} or billed not in {None, 0.0}:
        raise AudioSongExecutionError(
            "acceptance-only route cannot claim provider GPU spend"
        )

    graph = await session.scalar(
        select(MediaAssetGraph)
        .where(
            MediaAssetGraph.id == row.graph_id,
            MediaAssetGraph.organization_id == row.organization_id,
        )
        .with_for_update()
    )
    node_rows = list(
        (
            await session.scalars(
                select(MediaAssetNode)
                .where(
                    MediaAssetNode.graph_id == row.graph_id,
                    MediaAssetNode.organization_id == row.organization_id,
                )
                .with_for_update()
            )
        ).all()
    )
    nodes = {node.logical_key: node for node in node_rows}
    required_keys = {"song", *(f"stem-{stem}" for stem in _REQUIRED_STEMS)}
    if graph is None or not required_keys.issubset(nodes):
        raise AudioSongExecutionError("open-song Media DAG inputs disappeared")
    for logical_key in required_keys:
        node = nodes[logical_key]
        if node.status != "planned" or node.storage_key or node.checksum:
            raise AudioSongExecutionError(
                "open-song Media DAG input is not fresh"
            )

    request_hash = row.provider_job_id_sha256[:16] if row.provider_job_id_sha256 else None
    source_items: dict[str, _StoredAudioArtifact] = {"song": song}
    source_items.update({f"stem-{stem}": manifest[stem] for stem in _REQUIRED_STEMS})
    for logical_key, item in source_items.items():
        node = nodes[logical_key]
        node.status = "completed"
        node.storage_backend = item["storage_backend"]
        node.storage_key = item["storage_key"]
        node.checksum = item["checksum"]
        node.size_bytes = item["size_bytes"]
        node.media_type = item["media_type"]
        node.source_metadata = {
            **dict(node.source_metadata or {}),
            "duration_seconds": item["duration_seconds"],
            "sample_rate_hz": item["sample_rate_hz"],
            "channels": item["channels"],
        }
        node.provenance = [
            *list(node.provenance or []),
            {
                "type": "governed-open-song-provider-output",
                "logical_key": logical_key,
                "route_id": row.route_id,
                "provider": row.provider,
                "model": row.model,
                "model_revision": row.model_revision,
                "language_model": row.language_model,
                "language_model_revision": row.language_model_revision,
                "source_commit": row.source_commit,
                "container_image_digest": row.container_image_digest,
                "separation_model": row.separation_model,
                "separation_source_commit": row.separation_source_commit,
                "separation_checkpoint_sha256": row.separation_checkpoint_sha256,
                "provider_job_hash": request_hash,
                "output_checksum": item["checksum"],
                "fencing_token": fencing_token,
                "synthetic_vocals": True,
                "ai_generated_disclosure_required": True,
                "completed_at": now.isoformat(),
            },
        ]

    row.full_song_storage_key = song["storage_key"]
    row.full_song_checksum = song["checksum"]
    row.full_song_size_bytes = song["size_bytes"]
    row.full_song_duration_seconds = song["duration_seconds"]
    row.full_song_media_type = song["media_type"]
    row.stem_manifest = manifest
    row.stem_count = len(manifest)
    row.actual_billed_seconds = billed
    row.actual_cost_usd = actual
    row.actual_cost_known = actual is not None
    row.provider_state = "completed"
    row.provider_completed_at = now
    row.status = "rendering"
    row.provider_metadata = {
        **dict(row.provider_metadata or {}),
        **_safe_provider_metadata(metadata),
        "full_song_sample_rate_hz": song["sample_rate_hz"],
        "full_song_channels": song["channels"],
        "stem_names": list(_REQUIRED_STEMS),
        "raw_title_returned": False,
        "raw_concept_returned": False,
        "raw_lyrics_returned": False,
    }
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None
    row.available_at = None
    row.updated_at = now

    graph.status = "rendering"
    graph.graph_metadata = {
        **dict(graph.graph_metadata or {}),
        "open_song_provider_output": {
            "execution_id": row.id,
            "route_id": row.route_id,
            "provider": row.provider,
            "model": row.model,
            "model_revision": row.model_revision,
            "language_model": row.language_model,
            "language_model_revision": row.language_model_revision,
            "source_commit": row.source_commit,
            "container_image_digest": row.container_image_digest,
            "full_song_checksum": song["checksum"],
            "stem_checksums": {
                stem: manifest[stem]["checksum"] for stem in _REQUIRED_STEMS
            },
            "actual_billed_seconds": billed,
            "actual_cost_usd": actual,
            "actual_cost_known": actual is not None,
            "raw_title_returned": False,
            "raw_concept_returned": False,
            "raw_lyrics_returned": False,
            "ai_generated_disclosure_required": True,
        },
    }
    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            user_id=None,
            action="audio.open_song.provider_completed",
            resource_type="audio_song_execution",
            resource_id=row.id,
            details={
                "graph_id": row.graph_id,
                "route_id": row.route_id,
                "provider": row.provider,
                "model": row.model,
                "full_song_checksum": song["checksum"],
                "stem_checksums": {
                    stem: manifest[stem]["checksum"] for stem in _REQUIRED_STEMS
                },
                "fencing_token": fencing_token,
                "actual_billed_seconds": billed,
                "actual_cost_usd": actual,
            },
        )
    )
    await session.flush()
    return row


async def hold_audio_song_execution_for_review(
    session: AsyncSession,
    *,
    execution_id: str,
    worker_id: str,
    lease_token: str,
    fencing_token: int,
    error_code: str,
    error_metadata: dict[str, Any] | None = None,
    current: datetime | None = None,
) -> AudioSongExecution:
    """Stop automatic work after a durable but unresolved provider boundary."""

    now = current or _now()
    row = await session.scalar(
        select(AudioSongExecution)
        .where(AudioSongExecution.id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    _verify_lease(
        row,
        worker_id=worker_id,
        lease_token=lease_token,
        fencing_token=fencing_token,
        current=now,
    )
    code = _required(error_code, label="song review code", maximum=120)
    crossed = row.provider_state in {"submitting", "submitted", "running"}
    ambiguous = row.provider_state == "submitting" and not row.provider_job_id
    row.status = "needs_review"
    row.provider_state = "ambiguous" if ambiguous else "needs_review"
    row.error_code = code
    row.error_metadata = {
        **_safe_provider_metadata(error_metadata),
        "provider_boundary_crossed": crossed,
        "ambiguous_submission": ambiguous,
        "automatic_retry": False,
        "automatic_cross_provider_fallback": False,
        "manual_review_required": True,
    }
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None
    row.available_at = None
    row.completed_at = now
    row.updated_at = now
    session.add(
        AuditEvent(
            organization_id=row.organization_id,
            user_id=None,
            action="audio.song.needs_review",
            resource_type="audio_song_execution",
            resource_id=row.id,
            details={
                "route_id": row.route_id,
                "provider": row.provider,
                "provider_job_recorded": bool(row.provider_job_id),
                "error_code": code,
                "automatic_retry": False,
            },
        )
    )
    await session.flush()
    return row


async def fail_audio_song_execution(
    session: AsyncSession,
    *,
    execution_id: str,
    worker_id: str,
    lease_token: str,
    fencing_token: int,
    error_code: str,
    error_metadata: dict[str, Any] | None = None,
    ambiguous_submission: bool,
    current: datetime | None = None,
) -> AudioSongExecution:
    now = current or _now()
    row = await session.scalar(
        select(AudioSongExecution)
        .where(AudioSongExecution.id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    _verify_lease(
        row,
        worker_id=worker_id,
        lease_token=lease_token,
        fencing_token=fencing_token,
        current=now,
    )
    code = _required(error_code, label="song error code", maximum=120)
    crossed = row.provider_state in {"submitting", "submitted", "running"}
    ambiguous = bool(ambiguous_submission or (row.provider_state == "submitting" and not row.provider_job_id))
    row.status = "needs_review" if ambiguous else "failed"
    row.provider_state = "ambiguous" if ambiguous else "failed"
    row.error_code = code
    row.error_metadata = {
        **_safe_provider_metadata(error_metadata),
        "provider_boundary_crossed": crossed,
        "ambiguous_submission": ambiguous,
        "automatic_retry": False,
        "automatic_cross_provider_fallback": False,
    }
    row.lease_owner = None
    row.lease_token = None
    row.lease_expires_at = None
    row.available_at = None
    row.completed_at = now
    row.updated_at = now
    await session.flush()
    return row


async def recover_expired_audio_song_executions(
    session: AsyncSession,
    *,
    current: datetime | None = None,
) -> dict[str, int]:
    now = current or _now()
    rows = list(
        (
            await session.scalars(
                select(AudioSongExecution)
                .where(
                    AudioSongExecution.status == "running",
                    AudioSongExecution.lease_expires_at.is_not(None),
                    AudioSongExecution.lease_expires_at <= now,
                )
                .order_by(AudioSongExecution.created_at, AudioSongExecution.id)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    recovered = 0
    review = 0
    for row in rows:
        if row.provider_state == "submitting" and not row.provider_job_id:
            row.status = "needs_review"
            row.provider_state = "ambiguous"
            row.error_code = "expired_ambiguous_submission"
            row.error_metadata = {
                "ambiguous_submission": True,
                "automatic_retry": False,
                "automatic_cross_provider_fallback": False,
            }
            row.completed_at = now
            review += 1
        elif row.provider_state in {"not_started", "submitted", "running"}:
            row.status = "queued"
            row.available_at = now
            recovered += 1
        else:
            row.status = "failed"
            row.provider_state = "failed"
            row.error_code = "expired_invalid_provider_state"
            row.completed_at = now
        row.lease_owner = None
        row.lease_token = None
        row.lease_expires_at = None
        if row.status != "queued":
            row.available_at = None
        row.updated_at = now
    await session.flush()
    return {"recovered": recovered, "needs_review": review, "observed": len(rows)}


async def finalize_audio_song_execution(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
    current: datetime | None = None,
) -> AudioSongExecution:
    now = current or _now()
    row = await session.scalar(
        select(AudioSongExecution)
        .where(
            AudioSongExecution.id == execution_id,
            AudioSongExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    if row.status == "completed":
        return row
    if row.status != "rendering" or row.provider_state != "completed":
        raise AudioSongExecutionError("open-song execution is not ready to finalize")
    graph = await session.get(MediaAssetGraph, row.graph_id)
    if graph is None or graph.status != "completed":
        raise AudioSongExecutionError("open-song media graph is not complete")
    final = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.graph_id == graph.id,
            MediaAssetNode.logical_key == "export",
        )
    )
    if (
        final is None
        or final.status != "completed"
        or not final.storage_key
        or not final.checksum
        or not final.size_bytes
    ):
        raise AudioSongExecutionError("open-song final export is incomplete")
    step = await session.scalar(
        select(MediaRenderStep).where(
            MediaRenderStep.graph_id == graph.id,
            MediaRenderStep.target_node_id == final.id,
        )
    )
    qa = ((step.result_metadata or {}).get("qa") or {}) if step else {}
    audio_analysis = qa.get("audio_analysis") if isinstance(qa, dict) else None
    if not isinstance(audio_analysis, dict) or audio_analysis.get("passed") is not True:
        raise AudioSongExecutionError("open-song final audio QA did not pass")
    asset = (
        await session.get(StudioAsset, row.studio_asset_id)
        if row.studio_asset_id
        else None
    )
    if row.studio_asset_id and (
        asset is None or int(asset.current_revision or 0) < 2
    ):
        raise AudioSongExecutionError("open-song Studio revision is incomplete")
    row.final_output_storage_key = final.storage_key
    row.final_output_checksum = final.checksum
    row.final_output_size_bytes = int(final.size_bytes)
    row.final_output_duration_seconds = float(
        (final.source_metadata or {}).get("duration_seconds")
        or row.full_song_duration_seconds
        or 0.0
    )
    row.final_audio_qa = audio_analysis
    row.studio_revision = int(asset.current_revision) if asset is not None else None
    row.status = "completed"
    row.completed_at = now
    row.updated_at = now
    await session.flush()
    return row


def _public_stems(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for stem in _REQUIRED_STEMS:
        item = value.get(stem)
        if not isinstance(item, dict):
            continue
        result[stem] = {
            "checksum": item.get("checksum"),
            "size_bytes": item.get("size_bytes"),
            "media_type": item.get("media_type"),
            "duration_seconds": item.get("duration_seconds"),
            "sample_rate_hz": item.get("sample_rate_hz"),
            "channels": item.get("channels"),
            "storage_locator_returned": False,
        }
    return result


async def audio_song_execution_snapshot(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
) -> dict[str, Any]:
    row = await session.scalar(
        select(AudioSongExecution).where(
            AudioSongExecution.id == execution_id,
            AudioSongExecution.organization_id == organization_id,
        )
    )
    if row is None:
        raise AudioSongExecutionError("open-song execution was not found")
    metadata = _safe_provider_metadata(row.provider_metadata or {})
    metadata.pop("balance_evidence_sha256", None)
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "workspace_id": row.workspace_id,
        "project_id": row.project_id,
        "studio_job_id": row.studio_job_id,
        "studio_asset_id": row.studio_asset_id,
        "graph_id": row.graph_id,
        "operation": row.operation,
        "route_id": row.route_id,
        "provider": row.provider,
        "model": row.model,
        "model_revision": row.model_revision,
        "language_model": row.language_model,
        "language_model_revision": row.language_model_revision,
        "source_commit": row.source_commit,
        "base_container_image_repository": row.base_container_image_repository,
        "base_container_image_index_digest": row.base_container_image_index_digest,
        "base_container_image_digest": row.base_container_image_digest,
        "endpoint_id_sha256": row.endpoint_id_sha256,
        "image_sbom_sha256": row.image_sbom_sha256,
        "handler_source_sha256": row.handler_source_sha256,
        "container_image_repository": row.container_image_repository,
        "container_image_index_digest": row.container_image_index_digest,
        "container_image_digest": row.container_image_digest,
        "endpoint_id_returned": False,
        "separation_model": row.separation_model,
        "separation_revision": row.separation_revision,
        "separation_source_commit": row.separation_source_commit,
        "separation_checkpoint_sha256": row.separation_checkpoint_sha256,
        "status": row.status,
        "provider_state": row.provider_state,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "polls": row.polls,
        "plan_checksum": row.plan_checksum,
        "runtime_evidence_sha256": row.runtime_evidence_sha256,
        "pricing_evidence_sha256": row.pricing_evidence_sha256,
        "license_evidence_sha256": row.license_evidence_sha256,
        "title_sha256": row.title_sha256,
        "title_characters": row.title_characters,
        "concept_sha256": row.concept_sha256,
        "concept_characters": row.concept_characters,
        "lyrics_sha256": row.lyrics_sha256,
        "lyrics_characters": row.lyrics_characters,
        "language": row.language,
        "duration_seconds": row.duration_seconds,
        "bpm": row.bpm,
        "musical_key": row.musical_key,
        "time_signature": row.time_signature,
        "output_profile_id": row.output_profile_id,
        "rights": {
            "basis": row.rights_basis,
            "evidence_present": row.rights_evidence_sha256 is not None,
            "evidence_sha256": row.rights_evidence_sha256,
            "commercial_use_authorized": row.commercial_use_authorized,
            "provider_terms_accepted": row.provider_terms_accepted,
            "ai_generated_disclosure_required": row.ai_generated_disclosure_required,
        },
        "cost": {
            "estimated_cost_usd": row.estimated_cost_usd,
            "max_cost_usd": row.max_cost_usd,
            "actual_cost_usd": row.actual_cost_usd,
            "actual_cost_known": row.actual_cost_known,
            "cost_basis": row.cost_basis,
            "rate_usd_per_second": row.rate_usd_per_second,
            "max_billed_seconds": row.max_billed_seconds,
            "actual_billed_seconds": row.actual_billed_seconds,
            "automatic_retry": False,
            "automatic_cross_provider_fallback": False,
        },
        "provider_job_recorded": row.provider_job_id is not None,
        "provider_job_id_sha256": row.provider_job_id_sha256,
        "provider_job_id_returned": False,
        "provider_metadata": metadata,
        "error_code": row.error_code,
        "error_metadata": _safe_provider_metadata(row.error_metadata or {}),
        "full_song": {
            "checksum": row.full_song_checksum,
            "size_bytes": row.full_song_size_bytes,
            "duration_seconds": row.full_song_duration_seconds,
            "media_type": row.full_song_media_type,
            "storage_locator_returned": False,
        },
        "stems": _public_stems(row.stem_manifest or {}),
        "stem_count": row.stem_count,
        "final_output": {
            "checksum": row.final_output_checksum,
            "size_bytes": row.final_output_size_bytes,
            "duration_seconds": row.final_output_duration_seconds,
            "audio_qa": row.final_audio_qa,
            "studio_revision": row.studio_revision,
            "storage_locator_returned": False,
        },
        "raw_title_returned": False,
        "raw_concept_returned": False,
        "raw_lyrics_returned": False,
        "credential_returned": False,
        "signed_url_returned": False,
        "voice_clone": False,
        "voice_transformation": False,
        "known_person_voice": False,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "completed_at": row.completed_at.isoformat()
        if row.completed_at is not None
        else None,
    }


async def audio_song_counts(
    session: AsyncSession,
    *,
    organization_id: str | None = None,
) -> dict[str, int]:
    base = select(func.count()).select_from(AudioSongExecution)
    if organization_id is not None:
        base = base.where(AudioSongExecution.organization_id == organization_id)
    total = int(await session.scalar(base) or 0)
    active_query = base.where(AudioSongExecution.status.in_(tuple(_ACTIVE)))
    review_query = base.where(AudioSongExecution.status == "needs_review")
    return {
        "total": total,
        "active": int(await session.scalar(active_query) or 0),
        "needs_review": int(await session.scalar(review_query) or 0),
    }
