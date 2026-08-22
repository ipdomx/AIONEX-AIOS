"""Phase 36G governed transcript-to-stock-voice dubbing orchestration."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aios.audio_factory import AudioRequest, build_audio_plan
from aios.phase36_audio_transcript import (
    GovernedAudioSource,
    TranscriptDocument,
    TranscriptSegment,
)
from app.db.models import (
    AudioDubbingExecution,
    AudioSpeechExecution,
    AuditEvent,
    MediaAssetGraph,
    MediaAssetNode,
    StudioAsset,
)
from app.services.audio_dubbing_providers import estimate_openai_translation_cost
from app.services.audio_dubbing_runtime import (
    AudioDubbingExecutionSpec,
    create_audio_dubbing_execution,
)
from app.services.audio_pipeline import (
    LocalAudioSourceBinding,
    create_local_audio_pipeline,
)
from app.services.audio_speech_pipeline import create_stock_speech_pipeline
from app.services.audio_speech_runtime import arm_audio_speech_execution
from app.services.media_graph_runtime import MediaGraphScope
from app.services.media_storage import MediaObjectStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class AudioDubbingPipelineError(RuntimeError):
    """The governed dubbing graph cannot be created or advanced safely."""


@dataclass(frozen=True, slots=True)
class AudioDubbingPipeline:
    execution_id: str
    estimated_translation_cost_usd: float
    max_translation_cost_usd: float
    speech_cost_upper_bound_usd: float
    max_total_cost_usd: float


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _document_from_private_payload(payload: dict[str, Any]) -> TranscriptDocument:
    if payload.get("schema") != "36G.transcript.private.v1":
        raise AudioDubbingPipelineError("private transcript schema is unsupported")
    raw_source = payload.get("source")
    raw_segments = payload.get("segments")
    if not isinstance(raw_source, dict) or not isinstance(raw_segments, list):
        raise AudioDubbingPipelineError("private transcript payload is incomplete")
    source = GovernedAudioSource(
        source_sha256=str(raw_source.get("source_sha256") or ""),
        locator_sha256=str(raw_source.get("locator_sha256") or ""),
        size_bytes=int(raw_source.get("size_bytes") or 0),
        media_type=str(raw_source.get("media_type") or ""),
        duration_ms=int(raw_source.get("duration_ms") or 0),
        sample_rate_hz=int(raw_source.get("sample_rate_hz") or 0),
        channels=int(raw_source.get("channels") or 0),
    )
    segments = tuple(
        TranscriptSegment(
            segment_id=str(item.get("segment_id") or ""),
            speaker_key=str(item.get("speaker_key") or ""),
            start_ms=int(item.get("start_ms") or 0),
            end_ms=int(item.get("end_ms") or 0),
            text=str(item.get("text") or ""),
            language=str(item.get("language") or ""),
            confidence=(
                float(item["confidence"])
                if item.get("confidence") is not None
                else None
            ),
        )
        for item in raw_segments
        if isinstance(item, dict)
    )
    return TranscriptDocument(
        source=source,
        language=str(payload.get("language") or ""),
        segments=segments,
        diarization_enabled=bool(payload.get("diarization_enabled")),
        transcript_kind=str(payload.get("transcript_kind") or "provider-neutral"),
    )


def load_private_transcript_document(
    *,
    store: MediaObjectStore,
    storage_key: str,
    object_checksum: str,
    object_size_bytes: int,
    max_bytes: int = 32 * 1024 * 1024,
) -> TranscriptDocument:
    body = store.get_bytes(storage_key, max_bytes=max_bytes)
    if len(body) != int(object_size_bytes):
        raise AudioDubbingPipelineError("private transcript object size changed")
    if hashlib.sha256(body).hexdigest() != object_checksum:
        raise AudioDubbingPipelineError("private transcript object checksum changed")
    if body.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                private = archive.read("transcript/private-transcript.json")
        except (KeyError, zipfile.BadZipFile) as exc:
            raise AudioDubbingPipelineError(
                "private transcript package is invalid"
            ) from exc
    else:
        private = body
    try:
        payload = json.loads(private.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AudioDubbingPipelineError("private transcript JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise AudioDubbingPipelineError("private transcript JSON is invalid")
    return _document_from_private_payload(payload)


def load_private_translation(
    *,
    store: MediaObjectStore,
    storage_key: str,
    checksum: str,
    size_bytes: int,
    max_bytes: int = 32 * 1024 * 1024,
) -> tuple[TranscriptDocument, dict[str, str]]:
    body = store.get_bytes(storage_key, max_bytes=max_bytes)
    if len(body) != int(size_bytes) or hashlib.sha256(body).hexdigest() != checksum:
        raise AudioDubbingPipelineError("private translation object changed")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise AudioDubbingPipelineError("private translation JSON is invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != "36G.dubbing-translation.private.v1"
    ):
        raise AudioDubbingPipelineError("private translation schema is unsupported")
    source = payload.get("source_transcript")
    plan = payload.get("dubbing_plan")
    if not isinstance(source, dict) or not isinstance(plan, dict):
        raise AudioDubbingPipelineError("private translation payload is incomplete")
    document = _document_from_private_payload(source)
    raw_segments = plan.get("segments")
    if not isinstance(raw_segments, list):
        raise AudioDubbingPipelineError("private translation segments are missing")
    translations: dict[str, str] = {}
    for item in raw_segments:
        if not isinstance(item, dict):
            raise AudioDubbingPipelineError("private translation segment is invalid")
        segment_id = str(item.get("source_segment_id") or "")
        text = str(item.get("translated_text") or "")
        if not segment_id or not text or segment_id in translations:
            raise AudioDubbingPipelineError("private translation segment is invalid")
        translations[segment_id] = text
    if set(translations) != {item.segment_id for item in document.segments}:
        raise AudioDubbingPipelineError("private translation coverage is incomplete")
    return document, translations


async def create_audio_dubbing_pipeline(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    source_transcript_node_id: str,
    document: TranscriptDocument,
    target_language: str,
    voice_bindings: dict[str, dict[str, str]],
    output_profile_id: str,
    idempotency_key: str,
    max_translation_cost_usd: float,
    per_segment_speech_cap_usd: float,
    max_total_cost_usd: float,
) -> AudioDubbingPipeline:
    source_node = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.id == source_transcript_node_id,
            MediaAssetNode.organization_id == scope.organization_id,
        )
    )
    if (
        source_node is None
        or source_node.status != "completed"
        or not source_node.storage_backend
        or not source_node.storage_key
        or not source_node.checksum
        or not source_node.size_bytes
        or source_node.media_type not in {"application/zip", "application/json"}
    ):
        raise AudioDubbingPipelineError("governed source transcript is unavailable")
    if document.checksum != (
        (source_node.operation_metadata or {}).get("transcript_checksum")
        or (source_node.source_metadata or {}).get("transcript_checksum")
    ):
        raise AudioDubbingPipelineError(
            "source transcript checksum is not bound to its node"
        )
    if set(voice_bindings) != set(document.speaker_keys):
        raise AudioDubbingPipelineError("stock voice bindings must cover every speaker")
    if not 0 < float(per_segment_speech_cap_usd) <= 0.10:
        raise AudioDubbingPipelineError(
            "per-segment speech cap is outside the launch range"
        )
    source_characters = sum(len(item.text) for item in document.segments)
    estimate, _pricing = estimate_openai_translation_cost(
        source_characters=source_characters,
        segment_count=len(document.segments),
    )
    speech_upper = round(len(document.segments) * per_segment_speech_cap_usd, 9)
    required_total = float(max_translation_cost_usd) + speech_upper
    if (
        estimate > float(max_translation_cost_usd)
        or required_total > float(max_total_cost_usd) + 1e-9
    ):
        raise AudioDubbingPipelineError(
            "dubbing budget does not cover the governed route"
        )
    row = await create_audio_dubbing_execution(
        session,
        spec=AudioDubbingExecutionSpec(
            organization_id=scope.organization_id,
            requested_by_id=scope.created_by_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            studio_job_id=scope.studio_job_id,
            studio_asset_id=scope.studio_asset_id,
            idempotency_key=idempotency_key,
            source_transcript_storage_backend=str(source_node.storage_backend),
            source_transcript_storage_key=str(source_node.storage_key),
            source_transcript_object_checksum=str(source_node.checksum),
            source_transcript_object_size_bytes=int(source_node.size_bytes),
            source_transcript_checksum=document.checksum,
            source_language=document.language,
            target_language=target_language,
            segment_count=len(document.segments),
            speaker_count=len(document.speaker_keys),
            voice_bindings=voice_bindings,
            output_profile_id=output_profile_id,
            estimated_translation_cost_usd=estimate,
            max_translation_cost_usd=max_translation_cost_usd,
            speech_cost_upper_bound_usd=speech_upper,
            max_total_cost_usd=max_total_cost_usd,
        ),
    )
    return AudioDubbingPipeline(
        execution_id=row.id,
        estimated_translation_cost_usd=float(row.estimated_translation_cost_usd),
        max_translation_cost_usd=float(row.max_translation_cost_usd),
        speech_cost_upper_bound_usd=float(row.speech_cost_upper_bound_usd),
        max_total_cost_usd=float(row.max_total_cost_usd),
    )


async def create_dubbing_speech_pipelines_from_private(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
    document: TranscriptDocument,
    translations: dict[str, str],
) -> tuple[dict[str, Any], ...]:
    row = await session.scalar(
        select(AudioDubbingExecution)
        .where(
            AudioDubbingExecution.id == execution_id,
            AudioDubbingExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None or row.status != "translated":
        raise AudioDubbingPipelineError("dubbing translation is not ready for speech")
    if row.speech_pipelines:
        return tuple(dict(item) for item in row.speech_pipelines)
    if document.checksum != row.source_transcript_checksum:
        raise AudioDubbingPipelineError("private translation source checksum changed")
    if set(translations) != {item.segment_id for item in document.segments}:
        raise AudioDubbingPipelineError("private translation coverage changed")
    per_segment_cap = round(
        float(row.speech_cost_upper_bound_usd) / len(document.segments), 9
    )
    pipelines: list[dict[str, Any]] = []
    for ordinal, segment in enumerate(document.segments):
        binding = dict(row.voice_bindings.get(segment.speaker_key) or {})
        voice = str(binding.get("voice") or "")
        translated_text = translations[segment.segment_id]
        plan = build_audio_plan(
            AudioRequest(
                title=f"Dubbing segment {ordinal + 1}",
                brief="Governed stock-voice segment for final dubbing mix.",
                operation="narration",
                use_case="localization",
                language=row.target_language,
                purpose="phase36g-complete-stock-voice-dubbing",
                script=translated_text,
                speaker_count=1,
                voice_mode="stock",
                source_count=0,
                output_profile_id="wav-pcm-48k-stereo",
                include_music=False,
                include_sfx=False,
            )
        )
        duration_seconds = max(2.0, (segment.end_ms - segment.start_ms) / 1_000 + 1.0)
        result = await create_stock_speech_pipeline(
            session,
            scope=MediaGraphScope(
                organization_id=organization_id,
                created_by_id=row.requested_by_id,
                workspace_id=row.workspace_id,
                project_id=row.project_id,
                studio_job_id=row.studio_job_id,
                studio_asset_id=None,
            ),
            plan=plan,
            provider="openai",
            model="gpt-4o-mini-tts-2025-12-15",
            voice=voice,
            instructions=(
                f"Speak naturally in {row.target_language}. Keep the complete line concise "
                f"and comfortably within {(segment.end_ms - segment.start_ms) / 1_000:.2f} seconds."
            ),
            speed=1.0,
            max_duration_seconds=duration_seconds,
            estimated_cost_usd=per_segment_cap,
            max_cost_usd=per_segment_cap,
            idempotency_key=(
                f"{row.idempotency_key}:speech:{segment.segment_id}:generation:0"
            ),
            max_attempts=1,
        )
        await arm_audio_speech_execution(
            session,
            execution_id=result.speech_execution_id,
            organization_id=organization_id,
            approved_max_cost_usd=per_segment_cap,
        )
        pipelines.append(
            {
                "segment_id": segment.segment_id,
                "speaker_key": segment.speaker_key,
                "voice": voice,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "target_duration_ms": segment.end_ms - segment.start_ms,
                "translated_text_sha256": _sha256_text(translated_text),
                "speech_execution_id": result.speech_execution_id,
                "speech_graph_id": result.graph_id,
                "speech_final_node_id": result.final_node_id,
                "status": "queued",
                "replacement_generation": 0,
                "max_cost_usd": per_segment_cap,
            }
        )
    row.speech_pipelines = pipelines
    row.status = "speech_running"
    row.speech_armed_at = datetime.now(UTC)
    await session.flush()
    return tuple(dict(item) for item in pipelines)


async def refresh_dubbing_speech_status(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
) -> str:
    row = await session.scalar(
        select(AudioDubbingExecution)
        .where(
            AudioDubbingExecution.id == execution_id,
            AudioDubbingExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AudioDubbingPipelineError("dubbing execution not found")
    if row.status not in {"speech_running", "speech_failed", "speech_completed"}:
        return row.status
    updated: list[dict[str, Any]] = []
    failed = False
    all_completed = True
    for item in list(row.speech_pipelines or []):
        entry = dict(item)
        execution = await session.get(
            AudioSpeechExecution, entry["speech_execution_id"]
        )
        graph = await session.get(MediaAssetGraph, entry["speech_graph_id"])
        if execution is None or graph is None:
            raise AudioDubbingPipelineError("dubbing speech pipeline disappeared")
        if execution.status in {"failed", "needs_review"} or graph.status == "failed":
            entry["status"] = "failed"
            entry["error_code"] = execution.error_code
            failed = True
            all_completed = False
        elif execution.status == "completed" and graph.status == "completed":
            entry["status"] = "completed"
            entry["provider_audio_duration_seconds"] = execution.output_duration_seconds
        else:
            entry["status"] = execution.status
            all_completed = False
        updated.append(entry)
    row.speech_pipelines = updated
    if failed:
        row.status = "speech_failed"
    elif all_completed:
        row.status = "speech_completed"
    else:
        row.status = "speech_running"
    await session.flush()
    return row.status


async def create_dubbing_final_pipeline(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
) -> str:
    row = await session.scalar(
        select(AudioDubbingExecution)
        .where(
            AudioDubbingExecution.id == execution_id,
            AudioDubbingExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None or row.status != "speech_completed":
        raise AudioDubbingPipelineError("dubbing speech segments are not complete")
    if row.final_graph_id:
        return row.final_graph_id
    bindings: list[LocalAudioSourceBinding] = []
    for item in list(row.speech_pipelines or []):
        entry = dict(item)
        execution = await session.get(
            AudioSpeechExecution, entry["speech_execution_id"]
        )
        node = await session.get(MediaAssetNode, entry["speech_final_node_id"])
        if execution is None or node is None or node.status != "completed":
            raise AudioDubbingPipelineError("dubbing speech output is unavailable")
        target_duration_ms = int(entry["target_duration_ms"])
        provider_duration_ms = int(
            round(float(execution.output_duration_seconds or 0) * 1_000)
        )
        # Stage 6 launch fits by padding only. It never truncates spoken words or
        # time-stretches a voice. Overlong speech is failed for explicit segment
        # replacement with a shorter translation or adjusted instruction.
        if provider_duration_ms <= 0 or provider_duration_ms > target_duration_ms + 100:
            raise AudioDubbingPipelineError(
                f"dubbing segment {entry['segment_id']} exceeds its timing window"
            )
        bindings.append(
            LocalAudioSourceBinding(
                node=node,
                offset_ms=int(entry["start_ms"]),
                gain_db=0.0,
                target_duration_ms=target_duration_ms,
            )
        )
    plan = build_audio_plan(
        AudioRequest(
            title="Governed complete stock-voice dubbing",
            brief="Align translated stock-voice segments and create the final mastered dub.",
            operation="cleanup-master",
            use_case="localization",
            language=row.target_language,
            purpose="phase36g-complete-stock-voice-dubbing",
            source_count=len(bindings),
            voice_mode="none",
            output_profile_id=row.output_profile_id,
            include_music=False,
            include_sfx=False,
        )
    )
    result = await create_local_audio_pipeline(
        session,
        scope=MediaGraphScope(
            organization_id=organization_id,
            created_by_id=row.requested_by_id,
            workspace_id=row.workspace_id,
            project_id=row.project_id,
            studio_job_id=row.studio_job_id,
            studio_asset_id=row.studio_asset_id,
        ),
        plan=plan,
        sources=tuple(bindings),
        idempotency_key=f"{row.idempotency_key}:final-audio",
    )
    row.final_graph_id = result.graph_id
    row.status = "rendering"
    row.render_started_at = datetime.now(UTC)
    await session.flush()
    return result.graph_id


async def finalize_dubbing_execution(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
) -> dict[str, Any]:
    row = await session.scalar(
        select(AudioDubbingExecution)
        .where(
            AudioDubbingExecution.id == execution_id,
            AudioDubbingExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None or row.status != "rendering" or not row.final_graph_id:
        raise AudioDubbingPipelineError("dubbing final graph is not rendering")
    graph = await session.get(MediaAssetGraph, row.final_graph_id)
    final = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.graph_id == row.final_graph_id,
            MediaAssetNode.logical_key == "export",
        )
    )
    if (
        graph is None
        or graph.status != "completed"
        or final is None
        or final.status != "completed"
    ):
        raise AudioDubbingPipelineError("dubbing final output is not complete")
    asset = (
        await session.get(StudioAsset, row.studio_asset_id)
        if row.studio_asset_id
        else None
    )
    if row.studio_asset_id and (asset is None or asset.current_revision < 2):
        raise AudioDubbingPipelineError("dubbing Studio revision did not materialize")
    row.status = "completed"
    row.final_output_storage_backend = final.storage_backend
    row.final_output_storage_key = final.storage_key
    row.final_output_checksum = final.checksum
    row.final_output_size_bytes = final.size_bytes
    duration_value = (
        final.timeline_metadata.get("duration_seconds")
        if isinstance(final.timeline_metadata, dict)
        else None
    )
    row.final_output_duration_seconds = (
        float(duration_value) if isinstance(duration_value, (int, float)) else None
    )
    speech_costs: list[float] = []
    speech_actual_known = True
    for item in list(row.speech_pipelines or []):
        execution = await session.get(AudioSpeechExecution, item["speech_execution_id"])
        if execution is None or execution.actual_cost_usd is None:
            speech_actual_known = False
            break
        speech_costs.append(float(execution.actual_cost_usd))
    row.actual_total_cost_usd = (
        round(float(row.actual_translation_cost_usd or 0) + sum(speech_costs), 9)
        if row.actual_translation_cost_usd is not None and speech_actual_known
        else None
    )
    row.completed_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=None,
            action="audio.dubbing.completed",
            resource_type="audio_dubbing_execution",
            resource_id=row.id,
            details={
                "source_transcript_checksum": row.source_transcript_checksum,
                "translation_checksum": row.translation_checksum,
                "final_graph_id": row.final_graph_id,
                "final_output_checksum": row.final_output_checksum,
                "segment_count": row.segment_count,
                "speaker_count": row.speaker_count,
            },
        )
    )
    await session.flush()
    return {
        "execution_id": row.id,
        "status": row.status,
        "final_graph_id": row.final_graph_id,
        "final_output_checksum": row.final_output_checksum,
        "final_output_storage_key": row.final_output_storage_key,
        "studio_revision": asset.current_revision if asset else None,
    }


async def replace_failed_dubbing_segment(
    session: AsyncSession,
    *,
    execution_id: str,
    organization_id: str,
    segment_id: str,
    document: TranscriptDocument,
    translations: dict[str, str],
) -> dict[str, Any]:
    row = await session.scalar(
        select(AudioDubbingExecution)
        .where(
            AudioDubbingExecution.id == execution_id,
            AudioDubbingExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if row is None or row.status != "speech_failed":
        raise AudioDubbingPipelineError(
            "dubbing project has no replaceable failed segment"
        )
    entries = [dict(item) for item in list(row.speech_pipelines or [])]
    index = next(
        (i for i, item in enumerate(entries) if item.get("segment_id") == segment_id),
        None,
    )
    if index is None or entries[index].get("status") != "failed":
        raise AudioDubbingPipelineError("requested dubbing segment is not failed")
    old = await session.get(AudioSpeechExecution, entries[index]["speech_execution_id"])
    if (
        old is None
        or old.provider_state in {"submitting", "ambiguous"}
        or old.status == "needs_review"
    ):
        raise AudioDubbingPipelineError("failed segment provider outcome is ambiguous")
    segment = next(
        (item for item in document.segments if item.segment_id == segment_id), None
    )
    if segment is None or set(translations) != {
        item.segment_id for item in document.segments
    }:
        raise AudioDubbingPipelineError(
            "replacement private translation evidence is invalid"
        )
    generation = int(entries[index].get("replacement_generation", 0)) + 1
    per_segment_cap = float(entries[index]["max_cost_usd"])
    voice = str(entries[index]["voice"])
    plan = build_audio_plan(
        AudioRequest(
            title=f"Replacement dubbing segment {segment_id}",
            brief="Replace only one definitively failed stock-voice segment.",
            operation="narration",
            use_case="localization",
            language=row.target_language,
            purpose="phase36g-dubbing-selective-recovery",
            script=translations[segment_id],
            speaker_count=1,
            voice_mode="stock",
            source_count=0,
            output_profile_id="wav-pcm-48k-stereo",
            include_music=False,
            include_sfx=False,
        )
    )
    result = await create_stock_speech_pipeline(
        session,
        scope=MediaGraphScope(
            organization_id=organization_id,
            created_by_id=row.requested_by_id,
            workspace_id=row.workspace_id,
            project_id=row.project_id,
            studio_job_id=row.studio_job_id,
            studio_asset_id=None,
        ),
        plan=plan,
        provider="openai",
        model="gpt-4o-mini-tts-2025-12-15",
        voice=voice,
        instructions=(
            f"Speak naturally in {row.target_language} and fit within "
            f"{(segment.end_ms - segment.start_ms) / 1_000:.2f} seconds."
        ),
        speed=1.0,
        max_duration_seconds=max(
            2.0, (segment.end_ms - segment.start_ms) / 1_000 + 1.0
        ),
        estimated_cost_usd=per_segment_cap,
        max_cost_usd=per_segment_cap,
        idempotency_key=(
            f"{row.idempotency_key}:speech:{segment_id}:generation:{generation}"
        ),
        max_attempts=1,
    )
    await arm_audio_speech_execution(
        session,
        execution_id=result.speech_execution_id,
        organization_id=organization_id,
        approved_max_cost_usd=per_segment_cap,
    )
    previous = dict(entries[index])
    entries[index].update(
        {
            "speech_execution_id": result.speech_execution_id,
            "speech_graph_id": result.graph_id,
            "speech_final_node_id": result.final_node_id,
            "status": "queued",
            "error_code": None,
            "replacement_generation": generation,
        }
    )
    row.replacement_history = [
        *list(row.replacement_history or []),
        {
            "segment_id": segment_id,
            "replaced_execution_id": previous.get("speech_execution_id"),
            "replacement_execution_id": result.speech_execution_id,
            "generation": generation,
        },
    ]
    row.speech_pipelines = entries
    row.status = "speech_running"
    await session.flush()
    return dict(entries[index])
