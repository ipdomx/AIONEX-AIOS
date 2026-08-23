"""Durable one-attempt authority for low-cost Google Lyria music generation.

The default Replicate route persists its Prediction ID before polling. A crash
after that durable ID resumes the same job and can never create a second paid
prediction. Only a pre-ID submitting lease may become ambiguous.
"""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.base import SessionLocal
from app.db.models import (
    AudioMusicExecution,
    AuditEvent,
    MediaAssetEdge,
    MediaAssetGraph,
    MediaAssetNode,
    User,
    uuid_str,
)
from app.services.audio_music_providers import ProviderMusicFailure, inspect_mp3_bytes
from app.services.media_storage import MediaObjectStore, media_object_store

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_MODEL_ROUTE = {
    "draft": ("lyria-3-clip-preview", 0.04),
    "final": ("lyria-3-pro-preview", 0.08),
}
_ALLOWED_COST_BASES = frozenset({"official_fixed_request"})
_MUSIC_MONTHLY_CAP_USD = 0.40
_MUSIC_MONTHLY_DRAFT_LIMIT = 10
_MUSIC_MONTHLY_FINAL_LIMIT = 3
_SENSITIVE_METADATA_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "secret",
    "prompt",
    "lyrics",
    "signed_url",
    "presigned",
    "output_url",
    "prediction_url",
)


class AudioMusicExecutionError(RuntimeError):
    """A governed music execution cannot proceed safely."""


class AudioMusicLeaseLost(AudioMusicExecutionError):
    """A stale worker attempted to act after lease reclamation."""


@dataclass(frozen=True, slots=True)
class AudioMusicClaim:
    execution_id: str
    lease_token: str
    fencing_token: int


@dataclass(frozen=True, slots=True)
class AudioMusicExecutionSpec:
    organization_id: str
    requested_by_id: str
    graph_id: str
    target_node_id: str
    plan_checksum: str
    runtime_evidence_sha256: str
    pricing_evidence_sha256: str
    prompt: str
    lyrics: str
    instrumental_only: bool
    rights_basis: str
    rights_evidence_sha256: str | None
    tier: str
    provider: str
    model: str
    idempotency_key: str
    request_options: dict[str, Any]
    final_generation_approved: bool
    final_approval_evidence_sha256: str | None
    prior_draft_checksum: str | None
    estimated_cost_usd: float
    max_cost_usd: float
    workspace_id: str | None = None
    project_id: str | None = None
    studio_job_id: str | None = None
    studio_asset_id: str | None = None
    operation: str = "generate-music"
    output_format: str = "mp3"
    max_attempts: int = 1


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _metadata_key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return (
        any(fragment in lowered for fragment in _SENSITIVE_METADATA_FRAGMENTS)
        or lowered == "token"
        or lowered.endswith("_token")
        or lowered.startswith("token_")
    )


def _safe_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, raw_value in list(payload.items())[:64]:
        key = str(raw_key)[:120]
        if _metadata_key_is_sensitive(key):
            continue
        if raw_value is None or isinstance(raw_value, (bool, int, float)):
            result[key] = raw_value
        elif isinstance(raw_value, str):
            result[key] = raw_value[:500]
        elif isinstance(raw_value, dict):
            result[key] = _safe_metadata(raw_value)
        elif isinstance(raw_value, list):
            items: list[Any] = []
            for item in raw_value[:32]:
                if item is None or isinstance(item, (bool, int, float)):
                    items.append(item)
                elif isinstance(item, str):
                    items.append(item[:500])
                elif isinstance(item, dict):
                    items.append(_safe_metadata(item))
            result[key] = items
    return result


def _validate_sha(value: str | None, label: str, *, required: bool) -> None:
    if value is None:
        if required:
            raise AudioMusicExecutionError(f"{label} checksum is required")
        return
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise AudioMusicExecutionError(f"{label} checksum is invalid")


def _validate_spec(spec: AudioMusicExecutionSpec) -> tuple[str, float]:
    if spec.provider not in {"gemini", "replicate"} or spec.operation != "generate-music":
        raise AudioMusicExecutionError("music provider/operation is outside the launch matrix")
    route = _MODEL_ROUTE.get(spec.tier)
    if route is None or route[0] != spec.model:
        raise AudioMusicExecutionError("music tier/model is outside the launch matrix")
    if spec.output_format != "mp3" or spec.max_attempts != 1:
        raise AudioMusicExecutionError("music output or attempt limit is invalid")
    if not 8 <= len(spec.idempotency_key.strip()) <= 160:
        raise AudioMusicExecutionError("music idempotency key is invalid")
    _validate_sha(spec.plan_checksum, "music plan", required=True)
    _validate_sha(spec.runtime_evidence_sha256, "music runtime evidence", required=True)
    _validate_sha(spec.pricing_evidence_sha256, "music pricing evidence", required=True)
    if not 8 <= len(spec.prompt.strip()) <= 12_000 or "\x00" in spec.prompt:
        raise AudioMusicExecutionError("music prompt is invalid")
    if spec.instrumental_only:
        if spec.lyrics.strip() or spec.rights_basis != "instrumental":
            raise AudioMusicExecutionError("instrumental music rights are inconsistent")
        _validate_sha(spec.rights_evidence_sha256, "music rights", required=False)
    else:
        if not 1 <= len(spec.lyrics.strip()) <= 20_000:
            raise AudioMusicExecutionError("governed lyrics are required")
        if spec.rights_basis not in {"original-user-owned", "licensed", "public-domain"}:
            raise AudioMusicExecutionError("vocal music rights basis is invalid")
        _validate_sha(spec.rights_evidence_sha256, "music rights", required=True)
    if spec.tier == "draft":
        if (
            spec.final_generation_approved
            or spec.final_approval_evidence_sha256 is not None
            or spec.prior_draft_checksum is not None
        ):
            raise AudioMusicExecutionError("draft music cannot claim final approval")
    else:
        if not spec.final_generation_approved:
            raise AudioMusicExecutionError("full-song music requires final approval")
        _validate_sha(
            spec.final_approval_evidence_sha256,
            "final approval evidence",
            required=True,
        )
        _validate_sha(spec.prior_draft_checksum, "prior draft", required=True)
    expected_cost = route[1]
    if round(float(spec.estimated_cost_usd), 9) != expected_cost:
        raise AudioMusicExecutionError("music estimate must match the official fixed price")
    if round(float(spec.max_cost_usd), 9) != expected_cost:
        raise AudioMusicExecutionError("music cap must match the official fixed price")
    return route


async def create_audio_music_execution(
    session: AsyncSession,
    *,
    spec: AudioMusicExecutionSpec,
) -> AudioMusicExecution:
    """Create an unarmed planned execution; no provider request is possible yet."""
    _validate_spec(spec)
    key = spec.idempotency_key.strip()
    existing = await session.scalar(
        select(AudioMusicExecution).where(
            AudioMusicExecution.organization_id == spec.organization_id,
            AudioMusicExecution.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.plan_checksum != spec.plan_checksum:
            raise AudioMusicExecutionError("music idempotency key conflicts with another plan")
        return existing
    graph = await session.scalar(
        select(MediaAssetGraph).where(
            MediaAssetGraph.id == spec.graph_id,
            MediaAssetGraph.organization_id == spec.organization_id,
        )
    )
    target = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.id == spec.target_node_id,
            MediaAssetNode.graph_id == spec.graph_id,
            MediaAssetNode.organization_id == spec.organization_id,
        )
    )
    if graph is None or target is None:
        raise AudioMusicExecutionError("music graph target is unavailable")
    if target.status != "planned" or target.storage_key or target.checksum:
        raise AudioMusicExecutionError("music target is not a fresh planned node")
    if target.node_type != "provider-music":
        raise AudioMusicExecutionError("music target node type is unsupported")
    prompt_sha = _hash_text(spec.prompt)
    lyrics_sha = _hash_text(spec.lyrics) if spec.lyrics else None
    target.prompt_metadata = {
        **(target.prompt_metadata or {}),
        "audio_music": {
            "provider": spec.provider,
            "model": spec.model,
            "operation": spec.operation,
            "tier": spec.tier,
            "prompt": spec.prompt,
            "prompt_sha256": prompt_sha,
            "lyrics": spec.lyrics,
            "lyrics_sha256": lyrics_sha,
            "instrumental_only": spec.instrumental_only,
        },
    }
    target.operation_metadata = {
        **(target.operation_metadata or {}),
        "executor": "audio-music-provider",
        "provider_operation": spec.operation,
        "tier": spec.tier,
        "output_format": spec.output_format,
        "request_options": dict(spec.request_options),
    }
    target.rights_metadata = {
        **(target.rights_metadata or {}),
        "rights_basis": spec.rights_basis,
        "rights_evidence_sha256": spec.rights_evidence_sha256,
        "instrumental_only": spec.instrumental_only,
        "named_artist_imitation": False,
        "preview_model": True,
        "synthid_disclosure_required": True,
    }
    row = AudioMusicExecution(
        id=uuid_str(),
        organization_id=spec.organization_id,
        workspace_id=spec.workspace_id,
        project_id=spec.project_id,
        studio_job_id=spec.studio_job_id,
        studio_asset_id=spec.studio_asset_id,
        graph_id=spec.graph_id,
        target_node_id=spec.target_node_id,
        requested_by_id=spec.requested_by_id,
        operation=spec.operation,
        provider=spec.provider,
        model=spec.model,
        tier=spec.tier,
        status="planned",
        provider_state="not_started",
        idempotency_key=key,
        plan_checksum=spec.plan_checksum,
        runtime_evidence_sha256=spec.runtime_evidence_sha256,
        pricing_evidence_sha256=spec.pricing_evidence_sha256,
        prompt_sha256=prompt_sha,
        prompt_characters=len(spec.prompt),
        lyrics_sha256=lyrics_sha,
        lyrics_characters=len(spec.lyrics),
        instrumental_only=spec.instrumental_only,
        rights_basis=spec.rights_basis,
        rights_evidence_sha256=spec.rights_evidence_sha256,
        final_generation_approved=spec.final_generation_approved,
        final_approval_evidence_sha256=spec.final_approval_evidence_sha256,
        prior_draft_checksum=spec.prior_draft_checksum,
        preview_model=True,
        synthid_disclosure_required=True,
        request_options=dict(spec.request_options),
        output_format=spec.output_format,
        attempts=0,
        max_attempts=1,
        fencing_token=0,
        provider_response_metadata={},
        usage_metadata={},
        estimated_cost_usd=float(spec.estimated_cost_usd),
        max_cost_usd=float(spec.max_cost_usd),
        actual_cost_usd=None,
        cost_basis="unknown",
        returned_text_characters=0,
    )
    session.add(row)
    await session.flush()
    return row


async def arm_audio_music_execution(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
    approved_max_cost_usd: float,
) -> AudioMusicExecution:
    row = await session.scalar(
        select(AudioMusicExecution)
        .where(
            AudioMusicExecution.id == execution_id,
            AudioMusicExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AudioMusicExecutionError("music execution not found")
    approved = round(float(approved_max_cost_usd), 9)
    configured = round(float(row.max_cost_usd), 9)
    if approved != configured or approved != round(float(row.estimated_cost_usd), 9):
        raise AudioMusicExecutionError("music user cost approval does not match fixed price")
    if row.status == "queued":
        return row
    if row.status != "planned" or row.provider_state != "not_started":
        raise AudioMusicExecutionError("only a fresh planned music execution may be armed")

    user = await session.scalar(
        select(User)
        .where(
            User.id == row.requested_by_id,
            User.organization_id == organization_id,
        )
        .with_for_update()
    )
    if user is None:
        raise AudioMusicExecutionError("music requesting user is unavailable")
    now = _now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prior_rows = list(
        (
            await session.scalars(
                select(AudioMusicExecution).where(
                    AudioMusicExecution.organization_id == organization_id,
                    AudioMusicExecution.requested_by_id == row.requested_by_id,
                    AudioMusicExecution.id != row.id,
                    AudioMusicExecution.armed_at.is_not(None),
                    AudioMusicExecution.armed_at >= month_start,
                )
            )
        ).all()
    )
    draft_count = sum(1 for item in prior_rows if item.tier == "draft")
    final_count = sum(1 for item in prior_rows if item.tier == "final")
    reserved_before = round(sum(float(item.max_cost_usd) for item in prior_rows), 9)
    if row.tier == "draft" and draft_count >= _MUSIC_MONTHLY_DRAFT_LIMIT:
        raise AudioMusicExecutionError("music monthly draft limit reached")
    if row.tier == "final" and final_count >= _MUSIC_MONTHLY_FINAL_LIMIT:
        raise AudioMusicExecutionError("music monthly final limit reached")
    reserved_after = round(reserved_before + configured, 9)
    if reserved_after > _MUSIC_MONTHLY_CAP_USD + 1e-9:
        raise AudioMusicExecutionError("music monthly cost cap would be exceeded")

    row.status = "queued"
    row.armed_at = now
    row.available_at = None
    row.error_code = None
    row.error_message = None
    row.request_options = {
        **dict(row.request_options or {}),
        "monthly_cost_gate": {
            "month_start": month_start.isoformat(),
            "monthly_cap_usd": _MUSIC_MONTHLY_CAP_USD,
            "draft_limit": _MUSIC_MONTHLY_DRAFT_LIMIT,
            "final_limit": _MUSIC_MONTHLY_FINAL_LIMIT,
            "draft_count_before": draft_count,
            "final_count_before": final_count,
            "reserved_before_usd": reserved_before,
            "reserved_after_usd": reserved_after,
        },
    }
    await session.flush()
    return row


class AudioMusicExecutionAuthority:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        store: MediaObjectStore | None = None,
        worker_id: str = "audio-music-worker",
        lease_seconds: int = 300,
        max_content_bytes: int = 67_108_864,
    ) -> None:
        if not 30 <= int(lease_seconds) <= 3_600:
            raise ValueError("music lease duration is outside the allowed range")
        self.session_factory = session_factory
        self.store = store or media_object_store()
        self.worker_id = worker_id
        self.lease_seconds = int(lease_seconds)
        self.max_content_bytes = int(max_content_bytes)

    async def reap_ambiguous_submissions(self, *, limit: int = 16) -> int:
        now = _now()
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(AudioMusicExecution)
                        .where(
                            AudioMusicExecution.status == "running",
                            AudioMusicExecution.provider_state == "submitting",
                            AudioMusicExecution.lease_expires_at.is_not(None),
                            AudioMusicExecution.lease_expires_at <= now,
                        )
                        .order_by(AudioMusicExecution.created_at, AudioMusicExecution.id)
                        .with_for_update(skip_locked=True)
                        .limit(max(1, min(100, int(limit))))
                    )
                ).all()
            )
            for row in rows:
                row.status = "failed"
                row.provider_state = "ambiguous"
                row.attempts = row.max_attempts
                row.error_code = "music_submission_ambiguous"
                row.error_message = (
                    "Music submission crossed the provider boundary without a durable result; "
                    "automatic resubmission is forbidden."
                )
                row.completed_at = now
                row.lease_token = None
                row.lease_owner = None
                row.lease_expires_at = None
                target = await session.get(MediaAssetNode, row.target_node_id)
                graph = await session.get(MediaAssetGraph, row.graph_id)
                if target is not None and target.status == "planned":
                    target.status = "failed"
                if graph is not None:
                    graph.status = "failed"
                session.add(
                    AuditEvent(
                        organization_id=row.organization_id,
                        user_id=None,
                        action="audio.music.submission_ambiguous",
                        resource_type="audio_music_execution",
                        resource_id=row.id,
                        details={
                            "provider": row.provider,
                            "model": row.model,
                            "tier": row.tier,
                            "attempts": row.attempts,
                            "fencing_token": row.fencing_token,
                            "automatic_resubmit": False,
                        },
                    )
                )
            if rows:
                await session.commit()
            return len(rows)

    async def claim(self) -> AudioMusicClaim | None:
        await self.reap_ambiguous_submissions()
        now = _now()
        parent_edge = aliased(MediaAssetEdge)
        parent_node = aliased(MediaAssetNode)
        async with self.session_factory() as session:
            blocked_parent = (
                select(parent_edge.id)
                .join(parent_node, parent_node.id == parent_edge.parent_node_id)
                .where(
                    parent_edge.child_node_id == AudioMusicExecution.target_node_id,
                    parent_node.status != "completed",
                )
                .exists()
            )
            fresh_or_reclaimable = and_(
                AudioMusicExecution.provider_state == "not_started",
                or_(
                    and_(
                        AudioMusicExecution.status == "queued",
                        AudioMusicExecution.attempts < AudioMusicExecution.max_attempts,
                        or_(
                            AudioMusicExecution.available_at.is_(None),
                            AudioMusicExecution.available_at <= now,
                        ),
                    ),
                    and_(
                        AudioMusicExecution.status == "running",
                        AudioMusicExecution.attempts <= AudioMusicExecution.max_attempts,
                        AudioMusicExecution.lease_expires_at.is_not(None),
                        AudioMusicExecution.lease_expires_at <= now,
                    ),
                ),
            )
            submitted_poll = and_(
                AudioMusicExecution.status == "running",
                AudioMusicExecution.provider_state == "submitted",
                AudioMusicExecution.provider_request_id.is_not(None),
                or_(
                    AudioMusicExecution.available_at.is_(None),
                    AudioMusicExecution.available_at <= now,
                ),
                or_(
                    AudioMusicExecution.lease_owner.is_(None),
                    AudioMusicExecution.lease_expires_at.is_(None),
                    AudioMusicExecution.lease_expires_at <= now,
                ),
            )
            row = await session.scalar(
                select(AudioMusicExecution)
                .where(or_(fresh_or_reclaimable, submitted_poll), ~blocked_parent)
                .order_by(AudioMusicExecution.created_at, AudioMusicExecution.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            initial_claim = row.provider_state == "not_started" and row.status == "queued"
            row.status = "running"
            if initial_claim:
                row.attempts = int(row.attempts) + 1
            row.fencing_token = int(row.fencing_token) + 1
            row.lease_token = str(uuid4())
            row.lease_owner = self.worker_id
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            row.available_at = None
            row.started_at = row.started_at or now
            row.error_code = None
            row.error_message = None
            await session.commit()
            return AudioMusicClaim(row.id, str(row.lease_token), int(row.fencing_token))

    def _require_owned(
        self,
        row: AudioMusicExecution | None,
        claim: AudioMusicClaim,
    ) -> AudioMusicExecution:
        if not (
            row is not None
            and row.status == "running"
            and row.lease_owner == self.worker_id
            and row.lease_token == claim.lease_token
            and int(row.fencing_token) == claim.fencing_token
        ):
            raise AudioMusicLeaseLost(claim.execution_id)
        assert row is not None
        return row

    async def mark_submission_started(self, claim: AudioMusicClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioMusicExecution)
                .where(AudioMusicExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_state != "not_started" or row.provider_request_id:
                raise AudioMusicExecutionError("music provider submission is not fresh")
            row.provider_state = "submitting"
            row.provider_submitted_at = row.provider_submitted_at or _now()
            await session.commit()

    async def mark_submitted(
        self,
        claim: AudioMusicClaim,
        *,
        provider_request_id: str,
        provider_response_metadata: dict[str, Any],
    ) -> None:
        job_id = provider_request_id.strip()
        if not job_id or len(job_id) > 200:
            raise AudioMusicExecutionError("music provider job ID is invalid")
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioMusicExecution)
                .where(AudioMusicExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_state != "submitting" or row.provider_request_id:
                raise AudioMusicExecutionError("music provider job cannot be recorded")
            row.provider_state = "submitted"
            row.provider_request_id = job_id
            row.provider_response_metadata = _safe_metadata(
                {**provider_response_metadata, "poll_count": 0}
            )
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = _now()
            await session.commit()

    async def mark_poll_pending(
        self,
        claim: AudioMusicClaim,
        *,
        provider_response_metadata: dict[str, Any],
        delay_seconds: int,
        max_polls: int,
    ) -> int:
        delay = max(1, min(60, int(delay_seconds)))
        ceiling = max(1, min(2_000, int(max_polls)))
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioMusicExecution)
                .where(AudioMusicExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_state != "submitted" or not row.provider_request_id:
                raise AudioMusicExecutionError("music polling requires a durable provider job")
            current = int((row.provider_response_metadata or {}).get("poll_count") or 0)
            count = current + 1
            if count > ceiling:
                raise AudioMusicExecutionError("music provider poll limit exhausted")
            row.provider_response_metadata = _safe_metadata(
                {**dict(row.provider_response_metadata or {}), **provider_response_metadata, "poll_count": count, "max_polls": ceiling}
            )
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = _now() + timedelta(seconds=delay)
            await session.commit()
            return count

    async def fail(
        self,
        claim: AudioMusicClaim,
        *,
        code: str,
        message: str,
        ambiguous_submission: bool = False,
    ) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioMusicExecution)
                .where(AudioMusicExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            row.status = "failed"
            row.provider_state = "ambiguous" if ambiguous_submission else "failed"
            row.attempts = row.max_attempts
            row.completed_at = _now()
            row.error_code = code.strip()[:120] or "music_execution_failure"
            row.error_message = message.strip()[:1_000] or "Music execution failed"
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            target = await session.get(MediaAssetNode, row.target_node_id)
            graph = await session.get(MediaAssetGraph, row.graph_id)
            if target is not None and target.status == "planned":
                target.status = "failed"
            if graph is not None:
                graph.status = "failed"
            await session.commit()

    async def complete_bytes(
        self,
        claim: AudioMusicClaim,
        *,
        body: bytes,
        content_type: str,
        provider_request_id: str | None,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float,
        cost_basis: str,
    ) -> dict[str, Any]:
        if cost_basis not in _ALLOWED_COST_BASES:
            raise AudioMusicExecutionError("music cost basis is unsupported")
        async with self.session_factory() as session:
            row = await session.get(AudioMusicExecution, claim.execution_id)
            row = self._require_owned(row, claim)
            if row.provider_state not in {"submitting", "submitted"}:
                raise AudioMusicExecutionError("music completion requires a submitted request")
            if row.provider_request_id and provider_request_id != row.provider_request_id:
                raise AudioMusicExecutionError("music completion provider job does not match")
            if content_type != "audio/mpeg" or row.output_format != "mp3":
                raise AudioMusicExecutionError("music content type is invalid")
            try:
                inspected = inspect_mp3_bytes(
                    body,
                    max_content_bytes=self.max_content_bytes,
                )
            except ProviderMusicFailure as exc:
                raise AudioMusicExecutionError("music MP3 validation failed") from exc
            expected = _MODEL_ROUTE[row.tier][1]
            actual = round(float(actual_cost_usd), 9)
            if actual != expected or actual > round(float(row.max_cost_usd), 9):
                raise AudioMusicExecutionError("music actual cost does not match approved fixed price")
            tier = row.tier
            key = (
                f"media/{row.organization_id}/music/{row.graph_id}/{row.target_node_id}/"
                f"f{claim.fencing_token}.mp3"
            )
        stored = await asyncio.to_thread(
            self.store.put_bytes,
            key,
            body,
            content_type,
            metadata={
                "execution-id": claim.execution_id,
                "fencing-token": str(claim.fencing_token),
                "tier": tier,
            },
        )
        try:
            return await self._complete_stored(
                claim,
                storage_backend=stored.backend,
                storage_key=stored.key,
                checksum=stored.sha256,
                size_bytes=stored.size_bytes,
                content_type=content_type,
                provider_request_id=provider_request_id,
                provider_response_metadata=_safe_metadata(
                    {**provider_response_metadata, **inspected}
                ),
                usage_metadata=_safe_metadata(usage_metadata),
                actual_cost_usd=actual,
                cost_basis=cost_basis,
            )
        except Exception:
            await asyncio.to_thread(self.store.delete, stored.key)
            raise

    async def _complete_stored(
        self,
        claim: AudioMusicClaim,
        *,
        storage_backend: str,
        storage_key: str,
        checksum: str,
        size_bytes: int,
        content_type: str,
        provider_request_id: str | None,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float,
        cost_basis: str,
    ) -> dict[str, Any]:
        completed = _now()
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioMusicExecution)
                .where(AudioMusicExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            target = await session.scalar(
                select(MediaAssetNode)
                .where(
                    MediaAssetNode.id == row.target_node_id,
                    MediaAssetNode.graph_id == row.graph_id,
                    MediaAssetNode.organization_id == row.organization_id,
                )
                .with_for_update()
            )
            graph = await session.scalar(
                select(MediaAssetGraph)
                .where(
                    MediaAssetGraph.id == row.graph_id,
                    MediaAssetGraph.organization_id == row.organization_id,
                )
                .with_for_update()
            )
            if target is None or graph is None:
                raise AudioMusicExecutionError("music graph target disappeared")
            request_hash = (
                hashlib.sha256(provider_request_id.encode("utf-8")).hexdigest()[:16]
                if provider_request_id
                else None
            )
            target.status = "completed"
            target.storage_backend = storage_backend
            target.storage_key = storage_key
            target.checksum = checksum
            target.size_bytes = size_bytes
            target.media_type = content_type
            target.provenance = [
                *(target.provenance or []),
                {
                    "type": "provider-lyria-music",
                    "provider": row.provider,
                    "model": row.model,
                    "tier": row.tier,
                    "provider_request_hash": request_hash,
                    "prompt_sha256": row.prompt_sha256,
                    "lyrics_sha256": row.lyrics_sha256,
                    "output_checksum": checksum,
                    "fencing_token": claim.fencing_token,
                    "preview_model": True,
                    "completed_at": completed.isoformat(),
                },
            ]
            row.status = "completed"
            row.provider_state = "completed"
            row.provider_request_id = provider_request_id
            row.provider_response_metadata = dict(provider_response_metadata)
            row.usage_metadata = dict(usage_metadata)
            row.actual_cost_usd = float(actual_cost_usd)
            row.cost_basis = cost_basis
            row.output_storage_backend = storage_backend
            row.output_storage_key = storage_key
            row.output_checksum = checksum
            row.output_size_bytes = size_bytes
            nominal = provider_response_metadata.get("nominal_duration_seconds")
            row.output_duration_seconds = (
                float(nominal) if isinstance(nominal, (int, float)) else None
            )
            returned_sha = provider_response_metadata.get("returned_text_sha256")
            row.returned_text_sha256 = (
                str(returned_sha) if isinstance(returned_sha, str) else None
            )
            row.returned_text_characters = int(
                provider_response_metadata.get("returned_text_characters") or 0
            )
            row.completed_at = completed
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = None
            row.error_code = None
            row.error_message = None
            incomplete = int(
                await session.scalar(
                    select(func.count(MediaAssetNode.id)).where(
                        MediaAssetNode.graph_id == graph.id,
                        MediaAssetNode.status != "completed",
                    )
                )
                or 0
            )
            graph.status = "completed" if incomplete == 0 else "rendering"
            graph.graph_metadata = {
                **(graph.graph_metadata or {}),
                "music_execution": {
                    "execution_id": row.id,
                    "provider": row.provider,
                    "model": row.model,
                    "tier": row.tier,
                    "prompt_sha256": row.prompt_sha256,
                    "lyrics_sha256": row.lyrics_sha256,
                    "output_checksum": checksum,
                    "fixed_cost_usd": float(actual_cost_usd),
                    "preview_model": True,
                    "synthid_disclosure_required": True,
                },
            }
            session.add(
                AuditEvent(
                    organization_id=row.organization_id,
                    user_id=None,
                    action="audio.music.completed",
                    resource_type="audio_music_execution",
                    resource_id=row.id,
                    details={
                        "graph_id": row.graph_id,
                        "target_node_id": row.target_node_id,
                        "provider": row.provider,
                        "model": row.model,
                        "tier": row.tier,
                        "output_checksum": checksum,
                        "fencing_token": claim.fencing_token,
                        "fixed_cost_usd": float(actual_cost_usd),
                        "preview_model": True,
                    },
                )
            )
            await session.commit()
            return {
                "execution_id": row.id,
                "graph_id": row.graph_id,
                "target_node_id": row.target_node_id,
                "status": row.status,
                "provider_state": row.provider_state,
                "output_checksum": checksum,
                "storage_backend": storage_backend,
                "fixed_cost_usd": float(actual_cost_usd),
            }


async def audio_music_execution_snapshot(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
) -> dict[str, Any]:
    row = await session.scalar(
        select(AudioMusicExecution).where(
            AudioMusicExecution.id == execution_id,
            AudioMusicExecution.organization_id == organization_id,
        )
    )
    if row is None:
        raise AudioMusicExecutionError("music execution not found")
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "graph_id": row.graph_id,
        "target_node_id": row.target_node_id,
        "operation": row.operation,
        "provider": row.provider,
        "model": row.model,
        "tier": row.tier,
        "status": row.status,
        "provider_state": row.provider_state,
        "plan_checksum": row.plan_checksum,
        "runtime_evidence_sha256": row.runtime_evidence_sha256,
        "pricing_evidence_sha256": row.pricing_evidence_sha256,
        "prompt_sha256": row.prompt_sha256,
        "prompt_characters": row.prompt_characters,
        "lyrics_sha256": row.lyrics_sha256,
        "lyrics_characters": row.lyrics_characters,
        "instrumental_only": row.instrumental_only,
        "rights_basis": row.rights_basis,
        "rights_evidence_sha256": row.rights_evidence_sha256,
        "final_generation_approved": row.final_generation_approved,
        "final_approval_evidence_sha256": row.final_approval_evidence_sha256,
        "prior_draft_checksum_present": row.prior_draft_checksum is not None,
        "preview_model": row.preview_model,
        "synthid_disclosure_required": row.synthid_disclosure_required,
        "cost_policy": _safe_metadata(
            dict((row.request_options or {}).get("cost_policy") or {})
        ),
        "monthly_cost_gate": _safe_metadata(
            dict((row.request_options or {}).get("monthly_cost_gate") or {})
        ),
        "reuse_same_user_plan": bool(
            (row.request_options or {}).get("reuse_same_user_plan", True)
        ),
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "fencing_token": row.fencing_token,
        "estimated_cost_usd": row.estimated_cost_usd,
        "max_cost_usd": row.max_cost_usd,
        "actual_cost_usd": row.actual_cost_usd,
        "cost_basis": row.cost_basis,
        "output_checksum": row.output_checksum,
        "output_size_bytes": row.output_size_bytes,
        "output_duration_seconds": row.output_duration_seconds,
        "returned_text_sha256": row.returned_text_sha256,
        "returned_text_characters": row.returned_text_characters,
        "provider_request_recorded": bool(row.provider_request_id),
        "provider_job_sha256": (
            hashlib.sha256(row.provider_request_id.encode("utf-8")).hexdigest()
            if row.provider_request_id
            else None
        ),
        "provider_response_metadata": _safe_metadata(
            dict(row.provider_response_metadata or {})
        ),
        "usage_metadata": _safe_metadata(dict(row.usage_metadata or {})),
        "error_code": row.error_code,
        "credential_returned": False,
        "raw_prompt_returned": False,
        "raw_lyrics_returned": False,
        "raw_provider_text_returned": False,
        "automatic_retry": False,
    }
