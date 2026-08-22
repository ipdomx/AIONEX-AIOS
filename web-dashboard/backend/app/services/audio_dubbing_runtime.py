"""Durable Phase 36G stock-voice dubbing translation authority."""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from aios.phase36_audio_transcript import (
    StockVoiceBinding,
    TranscriptDocument,
    build_dubbing_plan,
)
from app.db.base import SessionLocal
from app.db.models import AudioDubbingExecution, AuditEvent, StudioAsset
from app.services.media_storage import MediaObjectStore, media_object_store
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_ALLOWED_MODEL = "gpt-5.6-luna"
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
    {"provider_usage_official_rates", "official_rate_cap"}
)
_SENSITIVE_METADATA_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "secret",
    "prompt",
    "text",
    "translation",
    "transcript",
    "signed_url",
    "presigned",
    "storage_key",
)


class AudioDubbingExecutionError(RuntimeError):
    """A governed dubbing execution cannot proceed safely."""


class AudioDubbingLeaseLost(AudioDubbingExecutionError):
    """A stale dubbing worker attempted to commit after fencing rotation."""


@dataclass(frozen=True, slots=True)
class AudioDubbingClaim:
    execution_id: str
    lease_token: str
    fencing_token: int


@dataclass(frozen=True, slots=True)
class AudioDubbingExecutionSpec:
    organization_id: str
    requested_by_id: str
    idempotency_key: str
    source_transcript_storage_backend: str
    source_transcript_storage_key: str
    source_transcript_object_checksum: str
    source_transcript_object_size_bytes: int
    source_transcript_checksum: str
    source_language: str
    target_language: str
    segment_count: int
    speaker_count: int
    voice_bindings: dict[str, dict[str, str]]
    output_profile_id: str
    estimated_translation_cost_usd: float
    max_translation_cost_usd: float
    speech_cost_upper_bound_usd: float
    max_total_cost_usd: float
    provider: str = "openai"
    model: str = _ALLOWED_MODEL
    workspace_id: str | None = None
    project_id: str | None = None
    studio_job_id: str | None = None
    studio_asset_id: str | None = None
    max_attempts: int = 1


def _now() -> datetime:
    return datetime.now(UTC)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for raw_key, raw_value in list(payload.items())[:64]:
        key = str(raw_key)[:120]
        lowered = key.lower()
        if any(fragment in lowered for fragment in _SENSITIVE_METADATA_FRAGMENTS):
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


def _validate_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise AudioDubbingExecutionError(f"{label} checksum is invalid")


def _validate_spec(spec: AudioDubbingExecutionSpec) -> None:
    if spec.provider != "openai" or spec.model != _ALLOWED_MODEL:
        raise AudioDubbingExecutionError(
            "dubbing translation provider/model is outside the launch matrix"
        )
    if not 8 <= len(spec.idempotency_key.strip()) <= 160:
        raise AudioDubbingExecutionError("dubbing idempotency key is invalid")
    _validate_hash(spec.source_transcript_object_checksum, "source transcript object")
    _validate_hash(spec.source_transcript_checksum, "source transcript")
    if not 1 <= int(spec.source_transcript_object_size_bytes) <= 32 * 1024 * 1024:
        raise AudioDubbingExecutionError(
            "source transcript object size is outside the allowed range"
        )
    if not spec.source_transcript_storage_backend or not spec.source_transcript_storage_key:
        raise AudioDubbingExecutionError("source transcript storage evidence is incomplete")
    if not spec.source_language or not spec.target_language:
        raise AudioDubbingExecutionError("dubbing language evidence is incomplete")
    if spec.source_language == spec.target_language:
        raise AudioDubbingExecutionError("dubbing target language must differ from source")
    if not 1 <= int(spec.segment_count) <= 16:
        raise AudioDubbingExecutionError("dubbing segment count is outside the allowed range")
    if not 1 <= int(spec.speaker_count) <= 8:
        raise AudioDubbingExecutionError("dubbing speaker count is outside the allowed range")
    if len(spec.voice_bindings) != spec.speaker_count:
        raise AudioDubbingExecutionError("dubbing voice bindings do not cover all speakers")
    for speaker_key, binding in spec.voice_bindings.items():
        if not speaker_key.startswith("speaker-") or not isinstance(binding, dict):
            raise AudioDubbingExecutionError("dubbing voice binding is invalid")
        voice = str(binding.get("voice") or "").strip().lower()
        evidence = str(binding.get("runtime_evidence_sha256") or "").strip().lower()
        if voice not in _ALLOWED_VOICES:
            raise AudioDubbingExecutionError("dubbing voice must be a built-in stock voice")
        _validate_hash(evidence, "stock voice runtime evidence")
        if binding.get("custom_voice") or binding.get("voice_clone") or binding.get(
            "voice_transformation"
        ):
            raise AudioDubbingExecutionError("custom or transformed dubbing voice is forbidden")
    if spec.output_profile_id not in {
        "wav-pcm-48k-stereo",
        "m4a-aac-48k-stereo",
        "webm-opus-48k-stereo",
    }:
        raise AudioDubbingExecutionError("dubbing output profile is unsupported")
    if spec.max_attempts != 1:
        raise AudioDubbingExecutionError("dubbing translation must use one attempt")
    costs = (
        spec.estimated_translation_cost_usd,
        spec.max_translation_cost_usd,
        spec.speech_cost_upper_bound_usd,
        spec.max_total_cost_usd,
    )
    if any(float(value) < 0 for value in costs):
        raise AudioDubbingExecutionError("dubbing cost cannot be negative")
    if spec.estimated_translation_cost_usd > spec.max_translation_cost_usd:
        raise AudioDubbingExecutionError("translation estimate exceeds its cap")
    required_total = (
        float(spec.max_translation_cost_usd)
        + float(spec.speech_cost_upper_bound_usd)
    )
    if required_total > float(spec.max_total_cost_usd) + 1e-9:
        raise AudioDubbingExecutionError("dubbing aggregate cap is insufficient")
    if spec.max_total_cost_usd > 5.0:
        raise AudioDubbingExecutionError("dubbing aggregate cap exceeds the launch ceiling")


async def create_audio_dubbing_execution(
    session: AsyncSession,
    *,
    spec: AudioDubbingExecutionSpec,
) -> AudioDubbingExecution:
    _validate_spec(spec)
    key = spec.idempotency_key.strip()
    existing = await session.scalar(
        select(AudioDubbingExecution).where(
            AudioDubbingExecution.organization_id == spec.organization_id,
            AudioDubbingExecution.idempotency_key == key,
        )
    )
    if existing is not None:
        immutable = (
            existing.source_transcript_checksum == spec.source_transcript_checksum
            and existing.source_language == spec.source_language
            and existing.target_language == spec.target_language
            and existing.provider == spec.provider
            and existing.model == spec.model
            and existing.voice_bindings == spec.voice_bindings
            and abs(float(existing.max_total_cost_usd) - float(spec.max_total_cost_usd))
            <= 1e-9
        )
        if not immutable:
            raise AudioDubbingExecutionError(
                "dubbing idempotency key conflicts with another request"
            )
        return existing
    if spec.studio_asset_id:
        asset = await session.scalar(
            select(StudioAsset).where(
                StudioAsset.id == spec.studio_asset_id,
                StudioAsset.organization_id == spec.organization_id,
            )
        )
        if asset is None:
            raise AudioDubbingExecutionError("dubbing Studio asset is unavailable")
    row = AudioDubbingExecution(
        organization_id=spec.organization_id,
        workspace_id=spec.workspace_id,
        project_id=spec.project_id,
        studio_job_id=spec.studio_job_id,
        studio_asset_id=spec.studio_asset_id,
        requested_by_id=spec.requested_by_id,
        status="planned",
        provider_state="not_started",
        idempotency_key=key,
        provider=spec.provider,
        model=spec.model,
        source_transcript_storage_backend=spec.source_transcript_storage_backend,
        source_transcript_storage_key=spec.source_transcript_storage_key,
        source_transcript_object_checksum=spec.source_transcript_object_checksum,
        source_transcript_object_size_bytes=spec.source_transcript_object_size_bytes,
        source_transcript_checksum=spec.source_transcript_checksum,
        source_language=spec.source_language,
        target_language=spec.target_language,
        segment_count=spec.segment_count,
        speaker_count=spec.speaker_count,
        voice_bindings=spec.voice_bindings,
        output_profile_id=spec.output_profile_id,
        attempts=0,
        max_attempts=1,
        fencing_token=0,
        provider_response_metadata={},
        usage_metadata={},
        estimated_translation_cost_usd=spec.estimated_translation_cost_usd,
        max_translation_cost_usd=spec.max_translation_cost_usd,
        actual_translation_cost_usd=None,
        speech_cost_upper_bound_usd=spec.speech_cost_upper_bound_usd,
        max_total_cost_usd=spec.max_total_cost_usd,
        actual_total_cost_usd=None,
        cost_basis="official_rate_cap",
        speech_pipelines=[],
        replacement_history=[],
    )
    session.add(row)
    await session.flush()
    return row


async def arm_audio_dubbing_execution(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
    approved_max_total_cost_usd: float,
) -> AudioDubbingExecution:
    row = await session.scalar(
        select(AudioDubbingExecution)
        .where(
            AudioDubbingExecution.id == execution_id,
            AudioDubbingExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AudioDubbingExecutionError("dubbing execution not found")
    if row.status == "queued":
        return row
    if row.status != "planned":
        raise AudioDubbingExecutionError("only planned dubbing execution may be armed")
    if abs(float(row.max_total_cost_usd) - float(approved_max_total_cost_usd)) > 1e-9:
        raise AudioDubbingExecutionError("operator dubbing cost approval does not match")
    required = float(row.max_translation_cost_usd) + float(
        row.speech_cost_upper_bound_usd
    )
    if required > float(approved_max_total_cost_usd) + 1e-9:
        raise AudioDubbingExecutionError("dubbing aggregate cost exceeds approval")
    row.status = "queued"
    row.armed_at = _now()
    row.available_at = None
    row.error_code = None
    row.error_message = None
    await session.flush()
    return row


class AudioDubbingExecutionAuthority:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        store: MediaObjectStore | None = None,
        worker_id: str = "audio-dubbing-worker",
        lease_seconds: int = 300,
    ) -> None:
        if not 30 <= lease_seconds <= 3_600:
            raise ValueError("dubbing lease duration is outside the allowed range")
        self.session_factory = session_factory
        self.store = store or media_object_store()
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def _require_owned(
        self,
        row: AudioDubbingExecution | None,
        claim: AudioDubbingClaim,
    ) -> AudioDubbingExecution:
        if not (
            row is not None
            and row.status == "running"
            and row.lease_owner == self.worker_id
            and row.lease_token == claim.lease_token
            and int(row.fencing_token) == claim.fencing_token
        ):
            raise AudioDubbingLeaseLost(claim.execution_id)
        return row

    async def claim(self) -> AudioDubbingClaim | None:
        now = _now()
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioDubbingExecution)
                .where(
                    or_(
                        and_(
                            AudioDubbingExecution.status == "queued",
                            AudioDubbingExecution.attempts
                            < AudioDubbingExecution.max_attempts,
                            or_(
                                AudioDubbingExecution.available_at.is_(None),
                                AudioDubbingExecution.available_at <= now,
                            ),
                        ),
                        and_(
                            AudioDubbingExecution.status == "running",
                            AudioDubbingExecution.lease_expires_at.is_not(None),
                            AudioDubbingExecution.lease_expires_at <= now,
                        ),
                    )
                )
                .order_by(
                    AudioDubbingExecution.created_at,
                    AudioDubbingExecution.id,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            if row.status == "running" and row.provider_state == "submitting":
                row.status = "needs_review"
                row.provider_state = "ambiguous"
                row.error_code = "provider_submission_ambiguous"
                row.error_message = (
                    "Translation provider outcome is ambiguous; automatic resubmission is forbidden"
                )
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
            row.error_code = None
            row.error_message = None
            await session.commit()
            return AudioDubbingClaim(row.id, str(row.lease_token), int(row.fencing_token))

    async def mark_submission_started(self, claim: AudioDubbingClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioDubbingExecution)
                .where(AudioDubbingExecution.id == claim.execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_state != "not_started":
                raise AudioDubbingExecutionError("translation submission marker is not fresh")
            if int(row.attempts) >= int(row.max_attempts):
                raise AudioDubbingExecutionError("translation attempt budget is exhausted")
            row.attempts = int(row.attempts) + 1
            row.provider_state = "submitting"
            row.provider_submitted_at = _now()
            await session.commit()

    async def fail(
        self,
        claim: AudioDubbingClaim,
        *,
        code: str,
        message: str,
        ambiguous: bool = False,
        safe_to_resubmit: bool = False,
    ) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(AudioDubbingExecution)
                .where(AudioDubbingExecution.id == claim.execution_id)
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
            row.error_code = code.strip()[:120] or "dubbing_translation_failure"
            row.error_message = message.strip()[:1_000] or "Dubbing translation failed"
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            await session.commit()

    async def complete_translation(
        self,
        claim: AudioDubbingClaim,
        *,
        document: TranscriptDocument,
        translations: dict[str, str],
        provider_request_id: str | None,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str,
    ) -> dict[str, Any]:
        if cost_basis not in _ALLOWED_COST_BASES:
            raise AudioDubbingExecutionError("translation cost basis is unsupported")
        async with self.session_factory() as session:
            row = await session.get(AudioDubbingExecution, claim.execution_id)
            row = self._require_owned(row, claim)
            if document.checksum != row.source_transcript_checksum:
                raise AudioDubbingExecutionError("source transcript checksum changed")
            if document.language != row.source_language:
                raise AudioDubbingExecutionError("source transcript language changed")
            if len(document.segments) != row.segment_count:
                raise AudioDubbingExecutionError("source transcript segment count changed")
            if len(document.speaker_keys) != row.speaker_count:
                raise AudioDubbingExecutionError("source transcript speaker count changed")
            bindings = {
                speaker: StockVoiceBinding(
                    speaker_key=speaker,
                    provider="openai",
                    model="gpt-4o-mini-tts-2025-12-15",
                    voice=str(row.voice_bindings[speaker]["voice"]),
                    runtime_evidence_sha256=str(
                        row.voice_bindings[speaker]["runtime_evidence_sha256"]
                    ),
                )
                for speaker in document.speaker_keys
            }
            plan = build_dubbing_plan(
                document,
                target_language=row.target_language,
                translations=translations,
                voice_bindings=bindings,
                output_profile_id=row.output_profile_id,
            )
            if actual_cost_usd is not None and actual_cost_usd > float(
                row.max_translation_cost_usd
            ) + 1e-9:
                raise AudioDubbingExecutionError("translation cost exceeded its cap")
            organization_id = row.organization_id
            execution_id = row.id

        private_payload = {
            "schema": "36G.dubbing-translation.private.v1",
            "source_transcript": document.private_payload(),
            "dubbing_plan": plan.private_payload(),
        }
        body = (
            json.dumps(
                private_payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        key = (
            f"media/{organization_id}/dubbing/{execution_id}/"
            f"f{claim.fencing_token}/translation.json"
        )
        stored = await asyncio.to_thread(
            self.store.put_bytes,
            key,
            body,
            "application/json",
            metadata={
                "execution-id": execution_id,
                "fencing-token": str(claim.fencing_token),
                "private": "true",
            },
        )
        completed = _now()
        try:
            async with self.session_factory() as session:
                row = await session.scalar(
                    select(AudioDubbingExecution)
                    .where(AudioDubbingExecution.id == claim.execution_id)
                    .with_for_update()
                )
                row = self._require_owned(row, claim)
                row.status = "translated"
                row.provider_state = "completed"
                row.provider_request_id = provider_request_id
                row.provider_response_metadata = _safe_metadata(
                    provider_response_metadata
                )
                row.usage_metadata = _safe_metadata(usage_metadata)
                row.actual_translation_cost_usd = actual_cost_usd
                row.cost_basis = cost_basis
                row.translation_storage_backend = stored.backend
                row.translation_storage_key = stored.key
                row.translation_checksum = stored.sha256
                row.translation_size_bytes = stored.size_bytes
                row.translation_text_sha256 = _sha256_text(
                    "\n".join(
                        translations[item.segment_id] for item in document.segments
                    )
                )
                row.translation_completed_at = completed
                row.lease_token = None
                row.lease_owner = None
                row.lease_expires_at = None
                row.available_at = None
                row.error_code = None
                row.error_message = None
                session.add(
                    AuditEvent(
                        organization_id=organization_id,
                        user_id=None,
                        action="audio.dubbing.translation.completed",
                        resource_type="audio_dubbing_execution",
                        resource_id=row.id,
                        details={
                            "provider": row.provider,
                            "model": row.model,
                            "source_transcript_checksum": row.source_transcript_checksum,
                            "translation_checksum": stored.sha256,
                            "segment_count": row.segment_count,
                            "speaker_count": row.speaker_count,
                            "fencing_token": claim.fencing_token,
                        },
                    )
                )
                await session.commit()
                return {
                    "execution_id": row.id,
                    "status": row.status,
                    "translation_checksum": stored.sha256,
                    "translation_storage_key": stored.key,
                    "dubbing_plan_checksum": plan.checksum,
                }
        except Exception as exc:
            cleanup_failed = False
            try:
                await asyncio.to_thread(self.store.delete, stored.key)
            except Exception:
                cleanup_failed = True
            if cleanup_failed:
                exc.add_note("translation rollback object cleanup failed: 1")
            raise


async def audio_dubbing_execution_snapshot(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
) -> dict[str, Any]:
    row = await session.scalar(
        select(AudioDubbingExecution).where(
            AudioDubbingExecution.id == execution_id,
            AudioDubbingExecution.organization_id == organization_id,
        )
    )
    if row is None:
        raise AudioDubbingExecutionError("dubbing execution not found")
    pipelines = [
        {
            "segment_id": item.get("segment_id"),
            "speaker_key": item.get("speaker_key"),
            "voice": item.get("voice"),
            "status": item.get("status"),
            "replacement_generation": item.get("replacement_generation", 0),
            "execution_id_sha256": (
                _sha256_text(str(item.get("speech_execution_id")))
                if item.get("speech_execution_id")
                else None
            ),
        }
        for item in list(row.speech_pipelines or [])
        if isinstance(item, dict)
    ]
    return {
        "schema": "36G.audio-dubbing-execution.public.v1",
        "execution_id": row.id,
        "status": row.status,
        "provider": row.provider,
        "model": row.model,
        "provider_state": row.provider_state,
        "provider_request_present": bool(row.provider_request_id),
        "provider_request_sha256": (
            _sha256_text(row.provider_request_id)
            if row.provider_request_id
            else None
        ),
        "source_transcript_checksum": row.source_transcript_checksum,
        "source_language": row.source_language,
        "target_language": row.target_language,
        "segment_count": row.segment_count,
        "speaker_count": row.speaker_count,
        "voice_mode": "stock",
        "voice_bindings": {
            speaker: {
                "voice": value.get("voice"),
                "custom_voice": False,
                "voice_clone": False,
                "voice_transformation": False,
                "synthetic_voice_disclosure_required": True,
            }
            for speaker, value in dict(row.voice_bindings or {}).items()
            if isinstance(value, dict)
        },
        "attempts": row.attempts,
        "max_attempts": row.max_attempts,
        "fencing_token": row.fencing_token,
        "estimated_translation_cost_usd": row.estimated_translation_cost_usd,
        "max_translation_cost_usd": row.max_translation_cost_usd,
        "actual_translation_cost_usd": row.actual_translation_cost_usd,
        "speech_cost_upper_bound_usd": row.speech_cost_upper_bound_usd,
        "max_total_cost_usd": row.max_total_cost_usd,
        "actual_total_cost_usd": row.actual_total_cost_usd,
        "cost_basis": row.cost_basis,
        "translation": {
            "checksum": row.translation_checksum,
            "size_bytes": row.translation_size_bytes,
            "text_sha256": row.translation_text_sha256,
            "storage_locator_returned": False,
            "raw_translation_returned": False,
        },
        "speech_pipelines": pipelines,
        "final_output": {
            "graph_id_sha256": (
                _sha256_text(row.final_graph_id) if row.final_graph_id else None
            ),
            "checksum": row.final_output_checksum,
            "size_bytes": row.final_output_size_bytes,
            "duration_seconds": row.final_output_duration_seconds,
            "storage_locator_returned": False,
        },
        "raw_source_transcript_returned": False,
        "raw_translation_returned": False,
        "provider_request_id_returned": False,
        "credential_returned": False,
        "secret_returned": False,
    }
