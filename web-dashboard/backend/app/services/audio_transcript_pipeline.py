"""Phase 36G governed source-audio to durable transcript-package pipeline."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.db.models import (
    AudioTranscriptExecution,
    MediaAssetEdge,
    MediaAssetGraph,
    MediaAssetNode,
    uuid_str,
)
from app.services.audio_transcript_providers import estimate_openai_transcription_cost
from app.services.audio_transcript_runtime import (
    AudioTranscriptExecutionSpec,
    create_audio_transcript_execution,
)
from app.services.media_graph_runtime import MediaGraphScope
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class AudioTranscriptPipelineError(RuntimeError):
    """The governed transcript graph cannot be created safely."""


@dataclass(frozen=True, slots=True)
class AudioTranscriptPipeline:
    graph_id: str
    source_node_id: str
    target_node_id: str
    execution_id: str
    estimated_cost_usd: float
    max_cost_usd: float


def _canonical_sha256(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


async def create_audio_transcript_pipeline(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    source_node_id: str,
    language: str,
    provider: str = "openai",
    model: str = "gpt-4o-mini-transcribe-2025-12-15",
    idempotency_key: str,
    max_cost_usd: float = 0.01,
    source_duration_ms: int,
    source_sample_rate_hz: int,
    source_channels: int,
) -> AudioTranscriptPipeline:
    """Create one unarmed provider transcript graph against a governed source node."""
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 160:
        raise AudioTranscriptPipelineError(
            "transcript pipeline idempotency key is invalid"
        )
    if provider != "openai" or model != "gpt-4o-mini-transcribe-2025-12-15":
        raise AudioTranscriptPipelineError(
            "transcript provider/model is outside the launch matrix"
        )
    if not language.strip() or len(language) > 32:
        raise AudioTranscriptPipelineError("transcript language is invalid")

    source = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.id == source_node_id,
            MediaAssetNode.organization_id == scope.organization_id,
        )
    )
    if (
        source is None
        or source.status != "completed"
        or not source.storage_backend
        or not source.storage_key
        or not source.checksum
        or not source.size_bytes
        or not source.media_type
    ):
        raise AudioTranscriptPipelineError("governed transcript source is unavailable")
    source_graph = await session.scalar(
        select(MediaAssetGraph).where(
            MediaAssetGraph.id == source.graph_id,
            MediaAssetGraph.organization_id == scope.organization_id,
        )
    )
    if source_graph is None:
        raise AudioTranscriptPipelineError(
            "governed transcript source graph is unavailable"
        )
    if (
        scope.workspace_id is not None
        and source_graph.workspace_id != scope.workspace_id
    ):
        raise AudioTranscriptPipelineError(
            "transcript source workspace scope is invalid"
        )
    if scope.project_id is not None and source_graph.project_id != scope.project_id:
        raise AudioTranscriptPipelineError("transcript source project scope is invalid")
    if source.media_type not in {"audio/wav", "audio/x-wav"}:
        raise AudioTranscriptPipelineError(
            "governed transcript source type is unsupported"
        )
    estimate, pricing = estimate_openai_transcription_cost(source_duration_ms)
    if estimate > max_cost_usd or max_cost_usd <= 0 or max_cost_usd > 1.0:
        raise AudioTranscriptPipelineError(
            "transcript estimate exceeds the configured cap"
        )

    graph_payload = {
        "schema": "36G.audio-transcript-graph.v1",
        "source_node_id": source.id,
        "source_graph_id": source.graph_id,
        "source_sha256": source.checksum,
        "source_size_bytes": int(source.size_bytes),
        "source_media_type": source.media_type,
        "source_duration_ms": source_duration_ms,
        "source_sample_rate_hz": source_sample_rate_hz,
        "source_channels": source_channels,
        "language": language,
        "provider": provider,
        "model": model,
        "estimated_cost_usd": estimate,
        "max_cost_usd": max_cost_usd,
        "pricing": pricing,
    }
    graph_checksum = _canonical_sha256(graph_payload)
    existing = await session.scalar(
        select(MediaAssetGraph).where(
            MediaAssetGraph.organization_id == scope.organization_id,
            MediaAssetGraph.idempotency_key == key,
        )
    )
    if existing is not None:
        execution = await session.scalar(
            select(AudioTranscriptExecution).where(
                AudioTranscriptExecution.graph_id == existing.id,
                AudioTranscriptExecution.organization_id == scope.organization_id,
            )
        )
        source_copy = await session.scalar(
            select(MediaAssetNode).where(
                MediaAssetNode.graph_id == existing.id,
                MediaAssetNode.logical_key == "source-audio",
            )
        )
        target = await session.scalar(
            select(MediaAssetNode).where(
                MediaAssetNode.graph_id == existing.id,
                MediaAssetNode.logical_key == "transcript-package",
            )
        )
        if execution is None or source_copy is None or target is None:
            raise AudioTranscriptPipelineError(
                "existing transcript pipeline is incomplete"
            )
        if (
            existing.graph_checksum != graph_checksum
            or source_copy.checksum != source.checksum
            or execution.provider != provider
            or execution.model != model
            or execution.language != language
            or abs(float(execution.max_cost_usd) - float(max_cost_usd)) > 1e-9
        ):
            raise AudioTranscriptPipelineError(
                "transcript idempotency key conflicts with another request"
            )
        return AudioTranscriptPipeline(
            existing.id,
            source_copy.id,
            target.id,
            execution.id,
            float(execution.estimated_cost_usd),
            float(execution.max_cost_usd),
        )

    graph = MediaAssetGraph(
        id=uuid_str(),
        organization_id=scope.organization_id,
        workspace_id=scope.workspace_id,
        project_id=scope.project_id,
        studio_job_id=scope.studio_job_id,
        studio_asset_id=scope.studio_asset_id,
        created_by_id=scope.created_by_id,
        title="Governed audio transcript and captions",
        asset_kind="transcript",
        output_profile="transcript-package-v1",
        status="planned",
        graph_version=1,
        idempotency_key=key,
        graph_checksum=graph_checksum,
        graph_metadata={
            "schema": "36G.audio-transcript-graph.v1",
            "plan_status": "planned",
            "render_status": "not_started",
            "provider_requests": 0,
            "provider_spend_usd": 0.0,
            "pricing": pricing,
            "raw_transcript_returned": False,
        },
        rights_metadata={
            "speaker_identity_mode": "pseudonymous",
            "voice_clone": False,
            "voice_transformation": False,
        },
        provenance=[
            {
                "type": "governed-audio-source",
                "source_node_id": source.id,
                "source_sha256": source.checksum,
            }
        ],
    )
    session.add(graph)
    await session.flush()

    source_copy = MediaAssetNode(
        id=uuid_str(),
        graph_id=graph.id,
        organization_id=scope.organization_id,
        created_by_id=scope.created_by_id,
        logical_key="source-audio",
        revision=1,
        node_type="governed-audio-source",
        media_type=source.media_type,
        status="completed",
        storage_backend=source.storage_backend,
        storage_key=source.storage_key,
        checksum=source.checksum,
        size_bytes=source.size_bytes,
        idempotency_key=hashlib.sha256(
            f"{graph.id}:source-audio:1".encode("utf-8")
        ).hexdigest(),
        source_metadata={
            "source_node_id": source.id,
            "duration_ms": source_duration_ms,
            "sample_rate_hz": source_sample_rate_hz,
            "channels": source_channels,
        },
        prompt_metadata={},
        rights_metadata=dict(source.rights_metadata or {}),
        provenance=[
            *(source.provenance or []),
            {
                "type": "reused-governed-audio-source",
                "source_graph_id": source.graph_id,
                "source_node_id": source.id,
                "checksum": source.checksum,
            },
        ],
        scene_metadata={},
        timeline_metadata={"duration_ms": source_duration_ms},
        operation_metadata={"operation": "transcript-source"},
    )
    target = MediaAssetNode(
        id=uuid_str(),
        graph_id=graph.id,
        organization_id=scope.organization_id,
        created_by_id=scope.created_by_id,
        logical_key="transcript-package",
        revision=1,
        node_type="transcript-package",
        media_type="application/zip",
        status="planned",
        idempotency_key=hashlib.sha256(
            f"{graph.id}:transcript-package:1".encode("utf-8")
        ).hexdigest(),
        source_metadata={},
        prompt_metadata={},
        rights_metadata={
            "raw_transcript_private": True,
            "public_snapshot_hash_only": True,
            "speaker_identity_mode": "pseudonymous",
        },
        provenance=[{"type": "phase36g-transcript-plan"}],
        scene_metadata={},
        timeline_metadata={"duration_ms": source_duration_ms},
        operation_metadata={
            "executor": "audio-transcript-provider",
            "operation": "transcribe",
            "provider": provider,
            "model": model,
            "language": language,
            "response_format": "json",
        },
    )
    session.add_all([source_copy, target])
    await session.flush()
    session.add(
        MediaAssetEdge(
            id=uuid_str(),
            graph_id=graph.id,
            organization_id=scope.organization_id,
            parent_node_id=source_copy.id,
            child_node_id=target.id,
            dependency_type="input",
            ordinal=0,
        )
    )
    execution = await create_audio_transcript_execution(
        session,
        spec=AudioTranscriptExecutionSpec(
            organization_id=scope.organization_id,
            requested_by_id=scope.created_by_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            studio_job_id=scope.studio_job_id,
            studio_asset_id=scope.studio_asset_id,
            graph_id=graph.id,
            target_node_id=target.id,
            provider=provider,
            model=model,
            idempotency_key=f"{key}:execution",
            source_storage_backend=str(source.storage_backend),
            source_storage_key=str(source.storage_key),
            source_checksum=str(source.checksum),
            source_size_bytes=int(source.size_bytes),
            source_media_type=str(source.media_type),
            source_duration_ms=source_duration_ms,
            source_sample_rate_hz=source_sample_rate_hz,
            source_channels=source_channels,
            language=language,
            response_format="json",
            estimated_cost_usd=estimate,
            max_cost_usd=max_cost_usd,
            max_attempts=1,
        ),
    )
    graph.status = "rendering"
    await session.flush()
    return AudioTranscriptPipeline(
        graph.id,
        source_copy.id,
        target.id,
        execution.id,
        estimate,
        max_cost_usd,
    )
