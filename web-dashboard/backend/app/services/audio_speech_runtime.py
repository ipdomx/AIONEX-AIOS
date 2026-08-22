"""Phase 36G durable stock-voice speech execution authority.

The synchronous speech endpoint has no durable provider job identifier. Therefore
submission is marked durably before HTTP, and an expired lease in ``submitting``
state is failed as ambiguous instead of being resubmitted automatically.
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

from app.db.base import SessionLocal
from app.db.models import (
    AudioSpeechExecution,
    AuditEvent,
    MediaAssetEdge,
    MediaAssetGraph,
    MediaAssetNode,
    uuid_str,
)
from app.services.audio_speech_providers import ProviderSpeechFailure, inspect_pcm_wav
from app.services.media_storage import MediaObjectStore, media_object_store
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_ALLOWED_MODELS = frozenset({"gpt-4o-mini-tts-2025-12-15"})
_ALLOWED_VOICES = frozenset(
    {
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "nova",
        "onyx",
        "sage",
        "shimmer",
        "verse",
        "marin",
        "cedar",
    }
)
_ALLOWED_COST_BASES = frozenset(
    {"unknown", "official_rate_cap", "official_provider_usage"}
)


class AudioSpeechExecutionError(RuntimeError):
    """Durable stock-speech execution cannot proceed safely."""


class AudioSpeechLeaseLost(AudioSpeechExecutionError):
    """A stale worker attempted to act on a reclaimed speech execution."""


@dataclass(frozen=True, slots=True)
class AudioSpeechClaim:
    execution_id: str
    lease_token: str
    fencing_token: int
    mode: str = "submit"


@dataclass(frozen=True, slots=True)
class AudioSpeechExecutionSpec:
    organization_id: str
    requested_by_id: str
    graph_id: str
    target_node_id: str
    provider: str
    model: str
    operation: str
    input_text: str
    voice: str
    instructions: str
    idempotency_key: str
    request_options: dict[str, Any]
    workspace_id: str | None = None
    project_id: str | None = None
    studio_job_id: str | None = None
    studio_asset_id: str | None = None
    output_format: str = "wav"
    speed: float = 1.0
    max_duration_seconds: float = 60.0
    estimated_cost_usd: float = 0.01
    max_cost_usd: float = 0.05
    max_attempts: int = 1


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_SENSITIVE_METADATA_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "secret",
    "input_text",
    "instructions",
    "prompt",
    "signed_url",
    "presigned",
)


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


def _validate_spec(spec: AudioSpeechExecutionSpec) -> None:
    if (
        spec.provider != "openai"
        or spec.model not in _ALLOWED_MODELS
        or spec.operation != "synthesize-speech"
    ):
        raise AudioSpeechExecutionError(
            "provider/model/operation is outside the governed stock-speech launch matrix"
        )
    if spec.voice not in _ALLOWED_VOICES:
        raise AudioSpeechExecutionError("stock speech voice is unsupported")
    if spec.output_format != "wav":
        raise AudioSpeechExecutionError("stock speech output must be WAV")
    if not 1 <= len(spec.input_text) <= 4_096:
        raise AudioSpeechExecutionError("stock speech input is outside the allowed range")
    if len(spec.instructions) > 4_096:
        raise AudioSpeechExecutionError("stock speech instructions are outside the allowed range")
    if not 0.25 <= float(spec.speed) <= 4.0:
        raise AudioSpeechExecutionError("stock speech speed is outside the allowed range")
    if not 1.0 <= float(spec.max_duration_seconds) <= 300.0:
        raise AudioSpeechExecutionError("stock speech duration cap is outside the allowed range")
    if not 8 <= len(spec.idempotency_key.strip()) <= 160:
        raise AudioSpeechExecutionError("stock speech idempotency key is invalid")
    if not 1 <= int(spec.max_attempts) <= 3:
        raise AudioSpeechExecutionError("stock speech retry limit is outside the allowed range")
    estimated = float(spec.estimated_cost_usd)
    maximum = float(spec.max_cost_usd)
    if estimated < 0 or maximum <= 0 or maximum > 1.0 or estimated > maximum:
        raise AudioSpeechExecutionError("stock speech cost cap is invalid")


async def create_audio_speech_execution(
    session: AsyncSession,
    *,
    spec: AudioSpeechExecutionSpec,
) -> AudioSpeechExecution:
    """Create a planned execution; no provider request is possible before arm."""
    _validate_spec(spec)
    key = spec.idempotency_key.strip()
    existing = await session.scalar(
        select(AudioSpeechExecution).where(
            AudioSpeechExecution.organization_id == spec.organization_id,
            AudioSpeechExecution.idempotency_key == key,
        )
    )
    if existing is not None:
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
        raise AudioSpeechExecutionError("stock speech graph target is unavailable")
    if target.status != "planned" or target.storage_key or target.checksum:
        raise AudioSpeechExecutionError("stock speech target is not a fresh planned node")
    if target.node_type not in {"provider-speech", "audio-provider"}:
        raise AudioSpeechExecutionError("stock speech target node type is unsupported")

    input_sha = _hash_text(spec.input_text)
    instruction_sha = _hash_text(spec.instructions) if spec.instructions else None
    target.prompt_metadata = {
        **(target.prompt_metadata or {}),
        "audio_speech": {
            "provider": spec.provider,
            "model": spec.model,
            "operation": spec.operation,
            "input_text": spec.input_text,
            "input_sha256": input_sha,
            "instructions": spec.instructions,
            "instructions_sha256": instruction_sha,
            "voice": spec.voice,
        },
    }
    target.operation_metadata = {
        **(target.operation_metadata or {}),
        "executor": "audio-speech-provider",
        "provider_operation": spec.operation,
        "output_format": spec.output_format,
        "voice": spec.voice,
        "speed": float(spec.speed),
        "max_duration_seconds": float(spec.max_duration_seconds),
        "request_options": dict(spec.request_options),
    }
    row = AudioSpeechExecution(
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
        voice=spec.voice,
        speed=float(spec.speed),
        status="planned",
        provider_state="not_started",
        idempotency_key=key,
        input_sha256=input_sha,
        instructions_sha256=instruction_sha,
        input_characters=len(spec.input_text),
        request_options=dict(spec.request_options),
        output_format=spec.output_format,
        max_duration_seconds=float(spec.max_duration_seconds),
        attempts=0,
        max_attempts=int(spec.max_attempts),
        fencing_token=0,
        provider_response_metadata={},
        usage_metadata={},
        estimated_cost_usd=float(spec.estimated_cost_usd),
        max_cost_usd=float(spec.max_cost_usd),
        actual_cost_usd=None,
        cost_basis="unknown",
    )
    session.add(row)
    await session.flush()
    return row


async def arm_audio_speech_execution(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
    approved_max_cost_usd: float,
) -> AudioSpeechExecution:
    row = await session.scalar(
        select(AudioSpeechExecution)
        .where(
            AudioSpeechExecution.id == execution_id,
            AudioSpeechExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AudioSpeechExecutionError("stock speech execution not found")
    approved = round(float(approved_max_cost_usd), 9)
    configured = round(float(row.max_cost_usd), 9)
    if approved != configured or approved < float(row.estimated_cost_usd):
        raise AudioSpeechExecutionError("stock speech owner cost approval does not match the execution cap")
    if row.status == "queued":
        return row
    if row.status != "planned" or row.provider_state != "not_started":
        raise AudioSpeechExecutionError("only a fresh planned speech execution may be armed")
    row.status = "queued"
    row.armed_at = _now()
    row.available_at = None
    row.error_code = None
    row.error_message = None
    await session.flush()
    return row


class AudioSpeechExecutionAuthority:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        store: MediaObjectStore | None = None,
        worker_id: str = "audio-speech-worker",
        lease_seconds: int = 300,
    ) -> None:
        if not 30 <= int(lease_seconds) <= 3_600:
            raise ValueError("stock speech lease duration is outside the allowed range")
        self.session_factory = session_factory
        self.store = store or media_object_store()
        self.worker_id = worker_id
        self.lease_seconds = int(lease_seconds)

    async def reap_ambiguous_submissions(self, *, limit: int = 16) -> int:
        now = _now()
        async with self.session_factory() as session:
            rows = list(
                (
                    await session.scalars(
                        select(AudioSpeechExecution)
                        .where(
                            AudioSpeechExecution.status == "running",
                            AudioSpeechExecution.provider_state == "submitting",
                            AudioSpeechExecution.lease_expires_at.is_not(None),
                            AudioSpeechExecution.lease_expires_at <= now,
                        )
                        .order_by(AudioSpeechExecution.created_at, AudioSpeechExecution.id)
                        .with_for_update(skip_locked=True)
                        .limit(max(1, min(100, int(limit))))
                    )
                ).all()
            )
            for row in rows:
                row.status = "failed"
                row.provider_state = "ambiguous"
                row.attempts = row.max_attempts
                row.error_code = "speech_submission_ambiguous"
                row.error_message = (
                    "Speech submission crossed the provider boundary without a durable result; "
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
                        action="audio.speech.submission_ambiguous",
                        resource_type="audio_speech_execution",
                        resource_id=row.id,
                        details={
                            "provider": row.provider,
                            "model": row.model,
                            "attempts": row.attempts,
                            "fencing_token": row.fencing_token,
                            "automatic_resubmit": False,
                        },
                    )
                )
            if rows:
                await session.commit()
            return len(rows)

    async def claim(self) -> AudioSpeechClaim | None:
        await self.reap_ambiguous_submissions()
        now = _now()
        parent_edge = aliased(MediaAssetEdge)
        parent_node = aliased(MediaAssetNode)
        async with self.session_factory() as session:
            blocked_parent = (
                select(parent_edge.id)
                .join(parent_node, parent_node.id == parent_edge.parent_node_id)
                .where(
                    parent_edge.child_node_id == AudioSpeechExecution.target_node_id,
                    parent_node.status != "completed",
                )
                .exists()
            )
            row = await session.scalar(
                select(AudioSpeechExecution)
                .where(
                    AudioSpeechExecution.attempts < AudioSpeechExecution.max_attempts,
                    AudioSpeechExecution.provider_state == "not_started",
                    or_(
                        and_(
                            AudioSpeechExecution.status == "queued",
                            or_(
                                AudioSpeechExecution.available_at.is_(None),
                                AudioSpeechExecution.available_at <= now,
                            ),
                        ),
                        and_(
                            AudioSpeechExecution.status == "running",
                            AudioSpeechExecution.lease_expires_at.is_not(None),
                            AudioSpeechExecution.lease_expires_at <= now,
                        ),
                    ),
                    ~blocked_parent,
                )
                .order_by(AudioSpeechExecution.created_at, AudioSpeechExecution.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = "running"
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
            return AudioSpeechClaim(
                execution_id=row.id,
                lease_token=str(row.lease_token),
                fencing_token=int(row.fencing_token),
            )

    def _owns(
        self,
        row: AudioSpeechExecution | None,
        claim: AudioSpeechClaim,
    ) -> bool:
        return bool(
            row is not None
            and row.status == "running"
            and row.lease_owner == self.worker_id
            and row.lease_token == claim.lease_token
            and int(row.fencing_token) == claim.fencing_token
        )

    def _require_owned(
        self,
        row: AudioSpeechExecution | None,
        claim: AudioSpeechClaim,
    ) -> AudioSpeechExecution:
        if not self._owns(row, claim):
            raise AudioSpeechLeaseLost(claim.execution_id)
        assert row is not None
        return row

    async def renew(self, claim: AudioSpeechClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioSpeechExecution)
                .where(AudioSpeechExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            row.lease_expires_at = _now() + timedelta(seconds=self.lease_seconds)
            await session.commit()

    async def mark_submission_started(self, claim: AudioSpeechClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioSpeechExecution)
                .where(AudioSpeechExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_state != "not_started" or row.provider_request_id:
                raise AudioSpeechExecutionError("stock speech provider submission is not fresh")
            row.provider_state = "submitting"
            row.provider_submitted_at = row.provider_submitted_at or _now()
            await session.commit()

    async def fail(
        self,
        claim: AudioSpeechClaim,
        *,
        code: str,
        message: str,
        safe_to_resubmit: bool = False,
        ambiguous_submission: bool = False,
    ) -> None:
        safe_code = code.strip()[:120] or "speech_execution_failure"
        safe_message = message.strip()[:1_000] or "Speech execution failed"
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioSpeechExecution)
                .where(AudioSpeechExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if ambiguous_submission:
                row.status = "failed"
                row.provider_state = "ambiguous"
                row.attempts = row.max_attempts
                row.completed_at = _now()
            elif safe_to_resubmit and int(row.attempts) < int(row.max_attempts):
                row.status = "queued"
                row.provider_state = "not_started"
                row.available_at = _now() + timedelta(seconds=min(300, 2 ** row.attempts))
            else:
                row.status = "failed"
                row.provider_state = "failed"
                row.completed_at = _now()
            row.error_code = safe_code
            row.error_message = safe_message
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            if row.status == "failed":
                target = await session.get(MediaAssetNode, row.target_node_id)
                graph = await session.get(MediaAssetGraph, row.graph_id)
                if target is not None and target.status == "planned":
                    target.status = "failed"
                if graph is not None:
                    graph.status = "failed"
            await session.commit()

    async def complete_bytes(
        self,
        claim: AudioSpeechClaim,
        *,
        body: bytes,
        content_type: str,
        provider_request_id: str | None,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str,
    ) -> dict[str, Any]:
        safe_basis = cost_basis.strip()[:64] or "unknown"
        if safe_basis not in _ALLOWED_COST_BASES:
            raise AudioSpeechExecutionError("stock speech cost basis is unsupported")
        async with self.session_factory() as session:
            row = await session.get(AudioSpeechExecution, claim.execution_id)
            row = self._require_owned(row, claim)
            if row.provider_state != "submitting":
                raise AudioSpeechExecutionError("stock speech completion requires a submitted request")
            if content_type != "audio/wav" or row.output_format != "wav":
                raise AudioSpeechExecutionError("stock speech content type is invalid")
            try:
                audio = inspect_pcm_wav(
                    body,
                    max_duration_seconds=float(row.max_duration_seconds),
                )
            except ProviderSpeechFailure as exc:
                raise AudioSpeechExecutionError("stock speech WAV validation failed") from exc
            if actual_cost_usd is not None:
                actual = float(actual_cost_usd)
                if actual < 0 or actual > float(row.max_cost_usd):
                    raise AudioSpeechExecutionError("stock speech actual cost exceeds the approved cap")
            key = (
                f"media/{row.organization_id}/speech/{row.graph_id}/{row.target_node_id}/"
                f"f{claim.fencing_token}.wav"
            )
        stored = await asyncio.to_thread(
            self.store.put_bytes,
            key,
            body,
            content_type,
            metadata={
                "execution-id": claim.execution_id,
                "fencing-token": str(claim.fencing_token),
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
                    {**provider_response_metadata, **audio}
                ),
                usage_metadata=_safe_metadata(usage_metadata),
                actual_cost_usd=actual_cost_usd,
                cost_basis=safe_basis,
            )
        except Exception:
            await asyncio.to_thread(self.store.delete, stored.key)
            raise

    async def _complete_stored(
        self,
        claim: AudioSpeechClaim,
        *,
        storage_backend: str,
        storage_key: str,
        checksum: str,
        size_bytes: int,
        content_type: str,
        provider_request_id: str | None,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str,
    ) -> dict[str, Any]:
        completed = _now()
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioSpeechExecution)
                .where(AudioSpeechExecution.id == claim.execution_id)
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
                raise AudioSpeechExecutionError("stock speech graph target disappeared")
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
                    "type": "provider-stock-speech",
                    "provider": row.provider,
                    "model": row.model,
                    "operation": row.operation,
                    "voice": row.voice,
                    "provider_request_hash": request_hash,
                    "input_sha256": row.input_sha256,
                    "output_checksum": checksum,
                    "fencing_token": claim.fencing_token,
                    "completed_at": completed.isoformat(),
                },
            ]
            row.status = "completed"
            row.provider_state = "completed"
            row.provider_request_id = provider_request_id
            row.provider_response_metadata = dict(provider_response_metadata)
            row.usage_metadata = dict(usage_metadata)
            row.actual_cost_usd = (
                float(actual_cost_usd) if actual_cost_usd is not None else None
            )
            row.cost_basis = cost_basis
            row.output_storage_backend = storage_backend
            row.output_storage_key = storage_key
            row.output_checksum = checksum
            row.output_size_bytes = size_bytes
            row.output_duration_seconds = float(
                provider_response_metadata.get("duration_seconds") or 0.0
            )
            row.completed_at = completed
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = None
            row.error_code = None
            row.error_message = None
            incomplete_nodes = int(
                await session.scalar(
                    select(func.count(MediaAssetNode.id)).where(
                        MediaAssetNode.graph_id == graph.id,
                        MediaAssetNode.status != "completed",
                    )
                )
                or 0
            )
            if incomplete_nodes == 0:
                graph.status = "completed"
            else:
                graph.status = "rendering"
            graph.graph_metadata = {
                **(graph.graph_metadata or {}),
                "speech_execution": {
                    "execution_id": row.id,
                    "provider": row.provider,
                    "model": row.model,
                    "voice": row.voice,
                    "input_sha256": row.input_sha256,
                    "output_checksum": checksum,
                    "estimated_cost_usd": float(row.estimated_cost_usd),
                    "max_cost_usd": float(row.max_cost_usd),
                    "actual_cost_usd": (
                        float(actual_cost_usd) if actual_cost_usd is not None else None
                    ),
                    "cost_basis": cost_basis,
                    "provider_usage_reported": bool(
                        usage_metadata.get("provider_usage_reported")
                    ),
                },
            }
            session.add(
                AuditEvent(
                    organization_id=row.organization_id,
                    user_id=None,
                    action="audio.speech.completed",
                    resource_type="audio_speech_execution",
                    resource_id=row.id,
                    details={
                        "graph_id": row.graph_id,
                        "target_node_id": row.target_node_id,
                        "provider": row.provider,
                        "model": row.model,
                        "voice": row.voice,
                        "output_checksum": checksum,
                        "fencing_token": claim.fencing_token,
                        "actual_cost_known": actual_cost_usd is not None,
                        "cost_basis": cost_basis,
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
                "duration_seconds": row.output_duration_seconds,
            }


async def audio_speech_execution_snapshot(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
) -> dict[str, Any]:
    row = await session.scalar(
        select(AudioSpeechExecution).where(
            AudioSpeechExecution.id == execution_id,
            AudioSpeechExecution.organization_id == organization_id,
        )
    )
    if row is None:
        raise AudioSpeechExecutionError("stock speech execution not found")
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "graph_id": row.graph_id,
        "target_node_id": row.target_node_id,
        "operation": row.operation,
        "provider": row.provider,
        "model": row.model,
        "voice": row.voice,
        "speed": row.speed,
        "status": row.status,
        "provider_state": row.provider_state,
        "input_sha256": row.input_sha256,
        "instructions_sha256": row.instructions_sha256,
        "input_characters": row.input_characters,
        "output_format": row.output_format,
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
        "provider_request_recorded": bool(row.provider_request_id),
        "provider_response_metadata": _safe_metadata(
            dict(row.provider_response_metadata or {})
        ),
        "usage_metadata": _safe_metadata(dict(row.usage_metadata or {})),
        "error_code": row.error_code,
        "credential_returned": False,
        "input_text_returned": False,
        "instructions_returned": False,
    }
