"""Durable Phase 36G governed transcription authority.

The provider request is synchronous and has no recoverable job identity. A lease
that expires after `provider_state=submitting` is therefore moved to
`needs_review`; automatic resubmission is forbidden.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import zipfile
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from aios.phase36_audio_transcript import (
    GovernedAudioSource,
    TranscriptDocument,
    TranscriptSegment,
    caption_manifest,
    render_srt,
    render_webvtt,
)
from app.db.base import SessionLocal
from app.db.models import (
    AudioTranscriptExecution,
    AuditEvent,
    MediaAssetGraph,
    MediaAssetNode,
    StudioAsset,
    StudioAssetRevision,
    uuid_str,
)
from app.services.media_storage import MediaObjectStore, media_object_store
from app.services.production_studio import slug
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MEDIA_TYPES = frozenset({"audio/wav", "audio/x-wav"})

_ALLOWED_COST_BASES = frozenset({"unknown", "official_estimated_per_minute"})
_SENSITIVE_METADATA_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "secret",
    "prompt",
    "text",
    "transcript",
    "signed_url",
    "presigned",
    "storage_key",
)


class AudioTranscriptExecutionError(RuntimeError):
    """A durable governed transcript operation cannot proceed safely."""


class AudioTranscriptLeaseLost(AudioTranscriptExecutionError):
    """A stale transcript worker attempted to commit after fencing rotation."""


@dataclass(frozen=True, slots=True)
class AudioTranscriptClaim:
    execution_id: str
    lease_token: str
    fencing_token: int


@dataclass(frozen=True, slots=True)
class AudioTranscriptExecutionSpec:
    organization_id: str
    requested_by_id: str
    graph_id: str
    target_node_id: str
    provider: str
    model: str
    idempotency_key: str
    source_storage_backend: str
    source_storage_key: str
    source_checksum: str
    source_size_bytes: int
    source_media_type: str
    source_duration_ms: int
    source_sample_rate_hz: int
    source_channels: int
    language: str
    workspace_id: str | None = None
    project_id: str | None = None
    studio_job_id: str | None = None
    studio_asset_id: str | None = None
    response_format: str = "json"
    estimated_cost_usd: float = 0.0
    max_cost_usd: float = 0.0
    max_attempts: int = 1


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _metadata_key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_METADATA_FRAGMENTS)


def _safe_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for raw_key, raw_value in list(payload.items())[:64]:
        key = str(raw_key)[:120]
        if _metadata_key_is_sensitive(key):
            continue
        if raw_value is None or isinstance(raw_value, (bool, int, float)):
            safe[key] = raw_value
        elif isinstance(raw_value, str):
            safe[key] = raw_value[:500]
        elif isinstance(raw_value, dict):
            safe[key] = _safe_metadata(raw_value)
        elif isinstance(raw_value, list):
            values: list[Any] = []
            for item in raw_value[:32]:
                if item is None or isinstance(item, (bool, int, float)):
                    values.append(item)
                elif isinstance(item, str):
                    values.append(item[:500])
                elif isinstance(item, dict):
                    values.append(_safe_metadata(item))
            safe[key] = values
    return safe


def _validate_spec(spec: AudioTranscriptExecutionSpec) -> None:
    if spec.provider != "openai" or spec.model != "gpt-4o-mini-transcribe-2025-12-15":
        raise AudioTranscriptExecutionError(
            "provider/model is outside the governed transcript launch matrix"
        )
    if spec.response_format != "json":
        raise AudioTranscriptExecutionError("transcript response format is unsupported")
    if spec.source_media_type not in _ALLOWED_MEDIA_TYPES:
        raise AudioTranscriptExecutionError(
            "transcript source media type is unsupported"
        )
    if not _SHA256.fullmatch(spec.source_checksum):
        raise AudioTranscriptExecutionError("transcript source checksum is invalid")
    if not 1 <= spec.source_size_bytes <= 20_971_520:
        raise AudioTranscriptExecutionError(
            "transcript source size is outside the allowed range"
        )
    if not 1 <= spec.source_duration_ms <= 600_000:
        raise AudioTranscriptExecutionError(
            "transcript source duration is outside the allowed range"
        )
    if not 8_000 <= spec.source_sample_rate_hz <= 192_000:
        raise AudioTranscriptExecutionError("transcript source sample rate is invalid")
    if not 1 <= spec.source_channels <= 8:
        raise AudioTranscriptExecutionError("transcript source channels are invalid")
    if not spec.language.strip() or len(spec.language) > 32:
        raise AudioTranscriptExecutionError("transcript language is invalid")
    if not 8 <= len(spec.idempotency_key.strip()) <= 160:
        raise AudioTranscriptExecutionError("transcript idempotency key is invalid")
    if spec.max_attempts != 1:
        raise AudioTranscriptExecutionError(
            "transcript execution must use exactly one attempt"
        )
    if spec.estimated_cost_usd < 0 or spec.max_cost_usd < 0:
        raise AudioTranscriptExecutionError("transcript cost cannot be negative")
    if spec.estimated_cost_usd > spec.max_cost_usd or spec.max_cost_usd > 1.0:
        raise AudioTranscriptExecutionError("transcript cost exceeds the governed cap")


async def create_audio_transcript_execution(
    session: AsyncSession,
    *,
    spec: AudioTranscriptExecutionSpec,
) -> AudioTranscriptExecution:
    """Create an unarmed transcript execution; provider spend remains impossible."""
    _validate_spec(spec)
    key = spec.idempotency_key.strip()
    existing = await session.scalar(
        select(AudioTranscriptExecution).where(
            AudioTranscriptExecution.organization_id == spec.organization_id,
            AudioTranscriptExecution.idempotency_key == key,
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
        raise AudioTranscriptExecutionError("transcript graph target is unavailable")
    if target.status != "planned" or target.storage_key or target.checksum:
        raise AudioTranscriptExecutionError(
            "transcript target is not a fresh planned node"
        )
    if target.node_type != "transcript-package":
        raise AudioTranscriptExecutionError(
            "transcript target node type is unsupported"
        )
    row = AudioTranscriptExecution(
        id=uuid_str(),
        organization_id=spec.organization_id,
        workspace_id=spec.workspace_id,
        project_id=spec.project_id,
        studio_job_id=spec.studio_job_id,
        studio_asset_id=spec.studio_asset_id,
        graph_id=spec.graph_id,
        target_node_id=spec.target_node_id,
        requested_by_id=spec.requested_by_id,
        operation="transcribe",
        provider=spec.provider,
        model=spec.model,
        status="planned",
        idempotency_key=key,
        source_storage_backend=spec.source_storage_backend,
        source_storage_key=spec.source_storage_key,
        source_checksum=spec.source_checksum,
        source_size_bytes=spec.source_size_bytes,
        source_media_type=spec.source_media_type,
        source_duration_ms=spec.source_duration_ms,
        source_sample_rate_hz=spec.source_sample_rate_hz,
        source_channels=spec.source_channels,
        language=spec.language,
        response_format=spec.response_format,
        attempts=0,
        max_attempts=spec.max_attempts,
        fencing_token=0,
        provider_state="not_started",
        provider_response_metadata={},
        usage_metadata={},
        estimated_cost_usd=float(spec.estimated_cost_usd),
        max_cost_usd=float(spec.max_cost_usd),
        actual_cost_usd=None,
        cost_basis="official_estimated_per_minute",
    )
    target.operation_metadata = {
        **(target.operation_metadata or {}),
        "executor": "audio-transcript-provider",
        "provider": spec.provider,
        "model": spec.model,
        "source_sha256": spec.source_checksum,
        "source_duration_ms": spec.source_duration_ms,
        "language": spec.language,
        "response_format": spec.response_format,
    }
    session.add(row)
    await session.flush()
    return row


async def arm_audio_transcript_execution(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
    approved_max_cost_usd: float,
) -> AudioTranscriptExecution:
    row = await session.scalar(
        select(AudioTranscriptExecution)
        .where(
            AudioTranscriptExecution.id == execution_id,
            AudioTranscriptExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AudioTranscriptExecutionError("transcript execution not found")
    if row.status == "queued":
        return row
    if row.status != "planned":
        raise AudioTranscriptExecutionError(
            "only planned transcript execution may be armed"
        )
    if abs(float(row.max_cost_usd) - float(approved_max_cost_usd)) > 1e-9:
        raise AudioTranscriptExecutionError(
            "operator transcript cost approval does not match"
        )
    if float(row.estimated_cost_usd) > float(approved_max_cost_usd):
        raise AudioTranscriptExecutionError(
            "transcript estimate exceeds operator approval"
        )
    row.status = "queued"
    row.armed_at = _now()
    row.available_at = None
    row.error_code = None
    row.error_message = None
    await session.flush()
    return row


class AudioTranscriptExecutionAuthority:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        store: MediaObjectStore | None = None,
        worker_id: str = "audio-transcript-worker",
        lease_seconds: int = 300,
    ) -> None:
        if not 30 <= lease_seconds <= 3600:
            raise ValueError("transcript lease duration is outside the allowed range")
        self.session_factory = session_factory
        self.store = store or media_object_store()
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def _owns(
        self,
        row: AudioTranscriptExecution | None,
        claim: AudioTranscriptClaim,
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
        row: AudioTranscriptExecution | None,
        claim: AudioTranscriptClaim,
    ) -> AudioTranscriptExecution:
        if not self._owns(row, claim):
            raise AudioTranscriptLeaseLost(claim.execution_id)
        assert row is not None
        return row

    async def claim(self) -> AudioTranscriptClaim | None:
        now = _now()
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioTranscriptExecution)
                .where(
                    AudioTranscriptExecution.operation == "transcribe",
                    or_(
                        and_(
                            AudioTranscriptExecution.status == "queued",
                            AudioTranscriptExecution.attempts
                            < AudioTranscriptExecution.max_attempts,
                            or_(
                                AudioTranscriptExecution.available_at.is_(None),
                                AudioTranscriptExecution.available_at <= now,
                            ),
                        ),
                        and_(
                            AudioTranscriptExecution.status == "running",
                            AudioTranscriptExecution.lease_expires_at.is_not(None),
                            AudioTranscriptExecution.lease_expires_at <= now,
                        ),
                    ),
                )
                .order_by(
                    AudioTranscriptExecution.created_at,
                    AudioTranscriptExecution.id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            if row.status == "running" and row.provider_state == "submitting":
                row.status = "needs_review"
                row.error_code = "provider_submission_ambiguous"
                row.error_message = "Transcript provider outcome is ambiguous; automatic resubmission is forbidden"
                row.lease_token = None
                row.lease_owner = None
                row.lease_expires_at = None
                row.completed_at = now
                await session.commit()
                return None
            row.status = "running"
            row.fencing_token = int(row.fencing_token) + 1
            row.lease_token = str(uuid4())
            row.lease_owner = self.worker_id
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            row.available_at = None
            row.started_at = row.started_at or now
            row.error_code = None
            row.error_message = None
            await session.commit()
            return AudioTranscriptClaim(
                row.id,
                str(row.lease_token),
                int(row.fencing_token),
            )

    async def mark_submission_started(self, claim: AudioTranscriptClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioTranscriptExecution)
                .where(AudioTranscriptExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_state != "not_started":
                raise AudioTranscriptExecutionError(
                    "transcript provider submission marker is not fresh"
                )
            if int(row.attempts) >= int(row.max_attempts):
                raise AudioTranscriptExecutionError(
                    "transcript provider attempt budget is exhausted"
                )
            row.attempts = int(row.attempts) + 1
            row.provider_state = "submitting"
            row.provider_submitted_at = _now()
            await session.commit()

    async def renew(self, claim: AudioTranscriptClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioTranscriptExecution)
                .where(AudioTranscriptExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            row.lease_expires_at = _now() + timedelta(seconds=self.lease_seconds)
            await session.commit()

    async def fail(
        self,
        claim: AudioTranscriptClaim,
        *,
        code: str,
        message: str,
        ambiguous: bool = False,
        safe_to_resubmit: bool = False,
    ) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioTranscriptExecution)
                .where(AudioTranscriptExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if ambiguous:
                row.status = "needs_review"
                row.provider_state = "ambiguous"
            elif safe_to_resubmit and int(row.attempts) < int(row.max_attempts):
                row.status = "queued"
                row.provider_state = "not_started"
                row.available_at = _now() + timedelta(seconds=2)
            else:
                row.status = "failed"
                row.provider_state = "failed"
                row.completed_at = _now()
            row.error_code = code.strip()[:120] or "transcript_provider_failure"
            row.error_message = (
                message.strip()[:1000] or "Transcript provider request failed"
            )
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            await session.commit()

    async def complete_text(
        self,
        claim: AudioTranscriptClaim,
        *,
        text: str,
        provider_request_id: str | None,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str,
    ) -> dict[str, Any]:
        normalized = "\n".join(
            line.rstrip() for line in text.replace("\r\n", "\n").split("\n")
        ).strip()
        if not 1 <= len(normalized) <= 2_000_000 or "\x00" in normalized:
            raise AudioTranscriptExecutionError("provider transcript text is invalid")
        if actual_cost_usd is not None:
            raise AudioTranscriptExecutionError(
                "transcript actual cost must remain unknown without authoritative usage"
            )
        if cost_basis not in _ALLOWED_COST_BASES:
            raise AudioTranscriptExecutionError("transcript cost basis is unsupported")

        async with self.session_factory() as session:
            row = await session.get(AudioTranscriptExecution, claim.execution_id)
            row = self._require_owned(row, claim)
            source = GovernedAudioSource(
                source_sha256=row.source_checksum,
                locator_sha256=_sha256_text(
                    f"{row.source_storage_backend}:{row.source_storage_key}"
                ),
                size_bytes=int(row.source_size_bytes),
                media_type=row.source_media_type,
                duration_ms=int(row.source_duration_ms),
                sample_rate_hz=int(row.source_sample_rate_hz),
                channels=int(row.source_channels),
            )
            document = TranscriptDocument(
                source=source,
                language=row.language,
                segments=(
                    TranscriptSegment(
                        segment_id="segment-001",
                        speaker_key="speaker-001",
                        start_ms=0,
                        end_ms=int(row.source_duration_ms),
                        text=normalized,
                        language=row.language,
                        confidence=None,
                    ),
                ),
                diarization_enabled=False,
            )
            graph_id = row.graph_id
            organization_id = row.organization_id
            target_node_id = row.target_node_id

        private_json = (
            json.dumps(
                document.private_payload(),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        webvtt = render_webvtt(document).encode("utf-8")
        srt = render_srt(document).encode("utf-8")
        manifest = (
            json.dumps(
                caption_manifest(document),
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        package_buffer = io.BytesIO()
        with zipfile.ZipFile(
            package_buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.writestr("transcript/private-transcript.json", private_json)
            archive.writestr("captions/captions.vtt", webvtt)
            archive.writestr("captions/captions.srt", srt)
            archive.writestr("captions/manifest.json", manifest)
        package = package_buffer.getvalue()
        base = f"media/{organization_id}/transcript/{graph_id}/f{claim.fencing_token}"
        outputs = (
            (f"{base}/private-transcript.json", private_json, "application/json"),
            (f"{base}/captions.vtt", webvtt, "text/vtt"),
            (f"{base}/captions.srt", srt, "application/x-subrip"),
            (f"{base}/transcript-package.zip", package, "application/zip"),
        )
        stored = []
        try:
            for key, body, content_type in outputs:
                stored.append(
                    await asyncio.to_thread(
                        self.store.put_bytes,
                        key,
                        body,
                        content_type,
                        metadata={
                            "execution-id": claim.execution_id,
                            "fencing-token": str(claim.fencing_token),
                        },
                    )
                )
            package_object = stored[-1]
            completed = _now()
            async with self.session_factory() as session:
                row = await session.scalar(
                    select(AudioTranscriptExecution)
                    .where(AudioTranscriptExecution.id == claim.execution_id)
                    .with_for_update()
                )
                row = self._require_owned(row, claim)
                target = await session.scalar(
                    select(MediaAssetNode)
                    .where(
                        MediaAssetNode.id == target_node_id,
                        MediaAssetNode.graph_id == graph_id,
                        MediaAssetNode.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                graph = await session.scalar(
                    select(MediaAssetGraph)
                    .where(
                        MediaAssetGraph.id == graph_id,
                        MediaAssetGraph.organization_id == organization_id,
                    )
                    .with_for_update()
                )
                if target is None or graph is None:
                    raise AudioTranscriptExecutionError(
                        "transcript graph target disappeared"
                    )
                public_document = document.public_snapshot()
                target.status = "completed"
                target.storage_backend = package_object.backend
                target.storage_key = package_object.key
                target.checksum = package_object.sha256
                target.size_bytes = package_object.size_bytes
                target.media_type = "application/zip"
                target.provenance = [
                    *(target.provenance or []),
                    {
                        "type": "provider-transcript-package",
                        "provider": row.provider,
                        "model": row.model,
                        "operation": row.operation,
                        "provider_request_hash": (
                            _sha256_text(provider_request_id)[:16]
                            if provider_request_id
                            else None
                        ),
                        "source_sha256": row.source_checksum,
                        "transcript_checksum": document.checksum,
                        "output_checksum": package_object.sha256,
                        "fencing_token": claim.fencing_token,
                        "completed_at": completed.isoformat(),
                    },
                ]
                row.status = "completed"
                row.provider_state = "completed"
                row.provider_request_id = provider_request_id
                row.provider_response_metadata = _safe_metadata(
                    provider_response_metadata
                )
                row.usage_metadata = _safe_metadata(usage_metadata)
                row.actual_cost_usd = None
                row.cost_basis = cost_basis
                row.output_storage_backend = package_object.backend
                row.output_storage_key = package_object.key
                row.output_checksum = package_object.sha256
                row.output_size_bytes = package_object.size_bytes
                row.transcript_checksum = document.checksum
                row.transcript_text_sha256 = _sha256_text(normalized)
                row.transcript_characters = len(normalized)
                row.segment_count = len(document.segments)
                row.speaker_count = len(document.speaker_keys)
                row.transcript_language = document.language
                row.completed_at = completed
                row.lease_token = None
                row.lease_owner = None
                row.lease_expires_at = None
                row.available_at = None
                row.error_code = None
                row.error_message = None
                graph.status = "completed"
                graph.graph_metadata = {
                    **(graph.graph_metadata or {}),
                    "completed_at": completed.isoformat(),
                    "final_node_id": target.id,
                    "final_checksum": package_object.sha256,
                    "transcript": public_document,
                    "caption_manifest": caption_manifest(document),
                }
                completion: dict[str, Any] = {}
                if graph.studio_asset_id:
                    asset = await session.scalar(
                        select(StudioAsset)
                        .where(
                            StudioAsset.id == graph.studio_asset_id,
                            StudioAsset.organization_id == organization_id,
                        )
                        .with_for_update()
                    )
                    if asset is None:
                        raise AudioTranscriptExecutionError(
                            "transcript Studio asset is unavailable"
                        )
                    revision_number = int(asset.current_revision) + 1
                    filename = (
                        f"{slug(graph.title)}-transcript-v{graph.graph_version}.zip"
                    )
                    revision_metadata = {
                        "audio_transcript_output": {
                            "graph_id": graph.id,
                            "graph_version": graph.graph_version,
                            "execution_id_hash": _sha256_text(row.id),
                            "provider": row.provider,
                            "model": row.model,
                            "source_sha256": row.source_checksum,
                            "transcript_checksum": document.checksum,
                            "transcript_text_sha256": row.transcript_text_sha256,
                            "segment_count": row.segment_count,
                            "speaker_count": row.speaker_count,
                            "language": row.transcript_language,
                            "caption_manifest": caption_manifest(document),
                            "raw_transcript_returned": False,
                            "storage_locator_returned": False,
                        }
                    }
                    revision = StudioAssetRevision(
                        id=uuid_str(),
                        organization_id=organization_id,
                        asset_id=asset.id,
                        job_id=graph.studio_job_id or asset.job_id,
                        created_by_id=graph.created_by_id,
                        revision_number=revision_number,
                        filename=filename,
                        media_type="application/zip",
                        storage_path=package_object.key,
                        checksum=package_object.sha256,
                        size_bytes=package_object.size_bytes,
                        change_note=(
                            f"Phase 36G governed transcript graph v{graph.graph_version}"
                        ),
                        revision_metadata=revision_metadata,
                        status="active",
                    )
                    session.add(revision)
                    asset.current_revision = revision_number
                    asset.filename = filename
                    asset.media_type = "application/zip"
                    asset.storage_path = package_object.key
                    asset.checksum = package_object.sha256
                    asset.size_bytes = package_object.size_bytes
                    asset.asset_metadata = {
                        **(asset.asset_metadata or {}),
                        **revision_metadata,
                    }
                    completion = {
                        "studio_asset_id": asset.id,
                        "studio_revision_id": revision.id,
                        "studio_revision_number": revision_number,
                    }
                    graph.graph_metadata = {
                        **(graph.graph_metadata or {}),
                        **completion,
                    }
                session.add(
                    AuditEvent(
                        organization_id=organization_id,
                        user_id=None,
                        action="audio.transcript.completed",
                        resource_type="audio_transcript_execution",
                        resource_id=row.id,
                        details={
                            "graph_id": graph.id,
                            "target_node_id": target.id,
                            "provider": row.provider,
                            "model": row.model,
                            "source_sha256": row.source_checksum,
                            "transcript_checksum": document.checksum,
                            "output_checksum": package_object.sha256,
                            "fencing_token": claim.fencing_token,
                        },
                    )
                )
                await session.commit()
                return {
                    "execution_id": row.id,
                    "graph_id": graph.id,
                    "target_node_id": target.id,
                    "status": row.status,
                    "transcript_checksum": document.checksum,
                    "output_checksum": package_object.sha256,
                    "stored_object_keys": [item.key for item in stored],
                    **completion,
                }
        except Exception as exc:
            cleanup_failures = 0
            for item in stored:
                try:
                    await asyncio.to_thread(self.store.delete, item.key)
                except Exception:
                    cleanup_failures += 1
            if cleanup_failures:
                exc.add_note(
                    f"transcript rollback object cleanup failures: {cleanup_failures}"
                )
            raise


async def audio_transcript_execution_snapshot(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
) -> dict[str, Any]:
    row = await session.scalar(
        select(AudioTranscriptExecution).where(
            AudioTranscriptExecution.id == execution_id,
            AudioTranscriptExecution.organization_id == organization_id,
        )
    )
    if row is None:
        raise AudioTranscriptExecutionError("transcript execution not found")
    return {
        "schema": "36G.audio-transcript-execution.public.v1",
        "execution_id": row.id,
        "graph_id": row.graph_id,
        "target_node_id": row.target_node_id,
        "operation": row.operation,
        "provider": row.provider,
        "model": row.model,
        "status": row.status,
        "provider_state": row.provider_state,
        "provider_request_present": bool(row.provider_request_id),
        "provider_request_hash": (
            _sha256_text(row.provider_request_id)[:16]
            if row.provider_request_id
            else None
        ),
        "source": {
            "sha256": row.source_checksum,
            "size_bytes": row.source_size_bytes,
            "media_type": row.source_media_type,
            "duration_ms": row.source_duration_ms,
            "sample_rate_hz": row.source_sample_rate_hz,
            "channels": row.source_channels,
            "storage_locator_returned": False,
        },
        "language": row.language,
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "fencing_token": row.fencing_token,
        "estimated_cost_usd": row.estimated_cost_usd,
        "max_cost_usd": row.max_cost_usd,
        "actual_cost_usd": row.actual_cost_usd,
        "actual_cost_known": row.actual_cost_usd is not None,
        "cost_basis": row.cost_basis,
        "transcript": {
            "checksum": row.transcript_checksum,
            "text_sha256": row.transcript_text_sha256,
            "characters": row.transcript_characters,
            "segment_count": row.segment_count,
            "speaker_count": row.speaker_count,
            "language": row.transcript_language,
            "raw_text_returned": False,
        },
        "output": {
            "checksum": row.output_checksum,
            "size_bytes": row.output_size_bytes,
            "storage_locator_returned": False,
        },
        "error_code": row.error_code,
        "armed_at": row.armed_at.isoformat() if row.armed_at else None,
        "provider_submitted_at": (
            row.provider_submitted_at.isoformat() if row.provider_submitted_at else None
        ),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "raw_transcript_returned": False,
        "credential_returned": False,
        "secret_returned": False,
    }
