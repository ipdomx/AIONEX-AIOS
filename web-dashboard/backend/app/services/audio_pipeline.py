"""Phase 36G local provider-neutral audio plan to Media DAG bridge."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from aios.audio_factory import AudioPlan
from app.db.models import MediaAssetGraph, MediaAssetNode
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph
from app.services.media_orchestrator import (
    MediaEdgeSpec,
    MediaGraphSpec,
    MediaNodeSpec,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_SOURCE_MEDIA_TYPES = frozenset(
    {"audio/wav", "audio/x-wav", "audio/mp4", "audio/webm", "audio/mpeg", "audio/ogg"}
)
_AUDIO_PROFILE_MAP = {
    "wav-pcm-48k-stereo": "audio-wav-pcm",
    "wav-pcm-48k-mono": "audio-wav-pcm-mono",
    "m4a-aac-48k-stereo": "audio-m4a-aac",
    "webm-opus-48k-stereo": "audio-webm-opus",
}
_INTERNAL_AUDIO_PROFILE = "audio-wav-pcm"


class AudioPipelineError(ValueError):
    """A local audio plan cannot safely enter the Media DAG."""


@dataclass(frozen=True, slots=True)
class LocalAudioSourceBinding:
    node: MediaAssetNode
    offset_ms: int = 0
    gain_db: float = 0.0
    target_duration_ms: int | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.offset_ms <= 60_000:
            raise AudioPipelineError("audio source offset is outside the allowed range")
        if not -24.0 <= float(self.gain_db) <= 24.0:
            raise AudioPipelineError("audio source gain is outside the allowed range")
        if self.target_duration_ms is not None and not 250 <= int(self.target_duration_ms) <= 300_000:
            raise AudioPipelineError("audio source target duration is outside the allowed range")


@dataclass(frozen=True, slots=True)
class LocalAudioPipelineResult:
    graph_id: str
    graph_checksum: str
    audio_plan_checksum: str
    final_node_id: str
    waveform_node_id: str
    source_node_ids: tuple[str, ...]
    output_profile: str
    external_requests: int = 0
    external_cost_usd: float = 0.0

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36G.local-audio-pipeline.v1",
            "graph_id": self.graph_id,
            "graph_checksum": self.graph_checksum,
            "audio_plan_checksum": self.audio_plan_checksum,
            "source_count": len(self.source_node_ids),
            "output_profile": self.output_profile,
            "external_requests": self.external_requests,
            "external_cost_usd": self.external_cost_usd,
            "render_status": "planned",
        }


def _validate_source(binding: LocalAudioSourceBinding, organization_id: str) -> None:
    node = binding.node
    if node.organization_id != organization_id:
        raise AudioPipelineError("audio source belongs to another organization")
    if node.status != "completed":
        raise AudioPipelineError("audio source is not completed")
    if node.media_type not in _ALLOWED_SOURCE_MEDIA_TYPES:
        raise AudioPipelineError("audio source media type is unsupported")
    if not node.storage_key or not node.storage_backend:
        raise AudioPipelineError("audio source storage evidence is incomplete")
    if not node.checksum or not _SHA256.fullmatch(str(node.checksum)):
        raise AudioPipelineError("audio source checksum evidence is invalid")
    if int(node.size_bytes or 0) <= 0:
        raise AudioPipelineError("audio source size evidence is invalid")


def _source_key(index: int) -> str:
    return f"source-{index:03d}"


def _cleanup_key(index: int) -> str:
    return f"cleanup-{index:03d}"


def _align_key(index: int) -> str:
    return f"align-{index:03d}"


def build_local_audio_graph_spec(
    plan: AudioPlan,
    *,
    sources: tuple[LocalAudioSourceBinding, ...],
    graph_version: int = 1,
) -> MediaGraphSpec:
    """Build a no-provider cleanup/mix/master/export graph.

    Stage 2 intentionally accepts only the local ``cleanup-master`` plan. Provider
    tasks such as speech, transcription, music, vocals or voice operations remain
    outside this path until separately live-proven.
    """
    if plan.request.operation != "cleanup-master":
        raise AudioPipelineError("local audio runtime accepts cleanup-master only")
    if plan.plan_status != "planned" or plan.external_gates:
        raise AudioPipelineError("audio plan still has an external gate")
    if plan.render_status != "not_started":
        raise AudioPipelineError("audio plan render state is not fresh")
    if not 1 <= len(sources) <= 8:
        raise AudioPipelineError("local audio runtime requires one to eight sources")
    if plan.request.source_count != len(sources):
        raise AudioPipelineError("audio plan source count does not match governed sources")
    source_ids = [binding.node.id for binding in sources]
    if len(source_ids) != len(set(source_ids)):
        raise AudioPipelineError("audio source nodes must be unique")
    output_profile = _AUDIO_PROFILE_MAP.get(plan.output_profile.profile_id)
    if output_profile is None:
        raise AudioPipelineError("audio output profile has no governed Media mapping")

    nodes: list[MediaNodeSpec] = []
    edges: list[MediaEdgeSpec] = []
    for index, binding in enumerate(sources, start=1):
        node = binding.node
        source_key = _source_key(index)
        cleanup_key = _cleanup_key(index)
        align_key = _align_key(index)
        nodes.extend(
            [
                MediaNodeSpec(
                    key=source_key,
                    node_type="audio-source",
                    media_type=node.media_type,
                    provenance=(
                        {
                            "type": "governed-audio-source",
                            "source_node_id": node.id,
                            "source_graph_id": node.graph_id,
                            "checksum": node.checksum,
                        },
                    ),
                    timeline_metadata={"ordinal": index - 1},
                ),
                MediaNodeSpec(
                    key=cleanup_key,
                    node_type="audio-cleanup",
                    media_type="audio/wav",
                    parameters={
                        "operation": "audio_cleanup",
                        "output_profile": _INTERNAL_AUDIO_PROFILE,
                        "highpass_hz": 70,
                        "lowpass_hz": 18_000,
                        "hardware_adapter": "software",
                    },
                    provenance=(
                        {
                            "type": "phase36g-local-audio-cleanup",
                            "audio_plan_checksum": plan.checksum,
                        },
                    ),
                ),
                MediaNodeSpec(
                    key=align_key,
                    node_type="audio-alignment",
                    media_type="audio/wav",
                    parameters={
                        "operation": "audio_align",
                        "output_profile": _INTERNAL_AUDIO_PROFILE,
                        "offset_ms": binding.offset_ms,
                        "gain_db": round(float(binding.gain_db), 3),
                        "target_duration_ms": binding.target_duration_ms,
                        "timing_fit_mode": (
                            "pad-to-window" if binding.target_duration_ms is not None else "none"
                        ),
                        "hardware_adapter": "software",
                    },
                    timeline_metadata={
                        "ordinal": index - 1,
                        "offset_ms": binding.offset_ms,
                        "target_duration_ms": binding.target_duration_ms,
                    },
                ),
            ]
        )
        edges.extend(
            [
                MediaEdgeSpec(source_key, cleanup_key, ordinal=0),
                MediaEdgeSpec(cleanup_key, align_key, ordinal=0),
                MediaEdgeSpec(align_key, "mix", ordinal=index - 1),
            ]
        )

    qa = plan.qa_contract
    analysis_parameters = {
        "target_integrated_lufs": qa.target_integrated_lufs,
        "max_true_peak_dbtp": qa.max_true_peak_dbtp,
        "max_loudness_range_lu": qa.max_loudness_range_lu,
        "loudness_tolerance_lu": 1.5,
        "silence_noise_db": -50.0,
        "silence_min_duration_seconds": 0.2,
    }
    nodes.extend(
        [
            MediaNodeSpec(
                key="mix",
                node_type="audio-mix",
                media_type="audio/wav",
                parameters={
                    "operation": "audio_mix",
                    "output_profile": _INTERNAL_AUDIO_PROFILE,
                    "hardware_adapter": "software",
                },
                provenance=(
                    {
                        "type": "phase36g-local-audio-mix",
                        "source_count": len(sources),
                    },
                ),
            ),
            MediaNodeSpec(
                key="master",
                node_type="audio-master",
                media_type="audio/wav",
                parameters={
                    "operation": "audio_master",
                    "output_profile": _INTERNAL_AUDIO_PROFILE,
                    "hardware_adapter": "software",
                    **analysis_parameters,
                },
                provenance=(
                    {
                        "type": "phase36g-local-audio-master",
                        "qa_schema": "36G.audio-qa.v1",
                    },
                ),
            ),
            MediaNodeSpec(
                key="waveform",
                node_type="audio-waveform",
                media_type="image/png",
                parameters={
                    "operation": "audio_waveform",
                    "output_profile": "image-png-lossless",
                    "width": 1_200,
                    "height": 320,
                    "color": "#38bdf8",
                    "hardware_adapter": "software",
                },
                provenance=(
                    {
                        "type": "phase36g-audio-waveform-evidence",
                        "audio_plan_checksum": plan.checksum,
                    },
                ),
            ),
            MediaNodeSpec(
                key="export",
                node_type="audio-export",
                media_type=plan.output_profile.media_type,
                parameters={
                    "operation": "audio_export",
                    "output_profile": output_profile,
                    "primary_input_index": 0,
                    "hardware_adapter": "software",
                    **analysis_parameters,
                },
                provenance=(
                    {
                        "type": "phase36g-local-audio-final-export",
                        "audio_plan_checksum": plan.checksum,
                        "provider_requests": 0,
                        "provider_cost_usd": 0.0,
                    },
                ),
            ),
        ]
    )
    edges.extend(
        [
            MediaEdgeSpec("mix", "master", ordinal=0),
            MediaEdgeSpec("master", "waveform", ordinal=0),
            MediaEdgeSpec("master", "export", ordinal=0),
            MediaEdgeSpec("waveform", "export", dependency_type="qa", ordinal=1),
        ]
    )
    return MediaGraphSpec(
        title=plan.request.title,
        asset_kind="mixed",
        nodes=tuple(nodes),
        edges=tuple(edges),
        output_profile=output_profile,
        graph_version=graph_version,
        rights_metadata={
            "schema": "36G.audio-rights-runtime.v1",
            "operation": plan.request.operation,
            "voice_rights_required": False,
            "provider_neutral": True,
        },
        provenance=(
            {
                "type": "phase36g-local-audio-pipeline",
                "audio_plan_checksum": plan.checksum,
                "external_requests": 0,
                "external_cost_usd": 0.0,
            },
        ),
    )


def _pipeline_fingerprint(
    *,
    plan: AudioPlan,
    spec: MediaGraphSpec,
    sources: tuple[LocalAudioSourceBinding, ...],
) -> str:
    payload = {
        "audio_plan_checksum": plan.checksum,
        "graph_spec_checksum": spec.checksum,
        "sources": [
            {
                "node_id": binding.node.id,
                "checksum": binding.node.checksum,
                "offset_ms": binding.offset_ms,
                "gain_db": round(float(binding.gain_db), 3),
            }
            for binding in sources
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


async def _result_for(
    session: AsyncSession,
    graph: MediaAssetGraph,
    *,
    plan: AudioPlan,
    source_ids: tuple[str, ...],
) -> LocalAudioPipelineResult:
    rows = {
        row.logical_key: row
        for row in (
            await session.scalars(
                select(MediaAssetNode).where(MediaAssetNode.graph_id == graph.id)
            )
        ).all()
    }
    final = rows.get("export")
    waveform = rows.get("waveform")
    if final is None or waveform is None:
        raise AudioPipelineError("audio pipeline graph is missing final nodes")
    return LocalAudioPipelineResult(
        graph_id=graph.id,
        graph_checksum=graph.graph_checksum,
        audio_plan_checksum=plan.checksum,
        final_node_id=final.id,
        waveform_node_id=waveform.id,
        source_node_ids=source_ids,
        output_profile=graph.output_profile,
    )


async def create_local_audio_pipeline(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    plan: AudioPlan,
    sources: tuple[LocalAudioSourceBinding, ...],
    idempotency_key: str,
) -> LocalAudioPipelineResult:
    key = idempotency_key.strip()
    if not key or len(key) > 160:
        raise AudioPipelineError("audio pipeline idempotency key is invalid")
    for binding in sources:
        _validate_source(binding, scope.organization_id)
    spec = build_local_audio_graph_spec(plan, sources=sources)
    fingerprint = _pipeline_fingerprint(plan=plan, spec=spec, sources=sources)
    existing = await session.scalar(
        select(MediaAssetGraph).where(
            MediaAssetGraph.organization_id == scope.organization_id,
            MediaAssetGraph.idempotency_key == key,
        )
    )
    source_ids = tuple(binding.node.id for binding in sources)
    if existing is not None:
        metadata = existing.graph_metadata or {}
        if (
            metadata.get("audio_pipeline_fingerprint") != fingerprint
            or metadata.get("audio_plan_checksum") != plan.checksum
        ):
            raise AudioPipelineError("audio pipeline idempotency key conflicts with another source")
        return await _result_for(
            session,
            existing,
            plan=plan,
            source_ids=source_ids,
        )

    graph = await create_media_graph(
        session,
        scope=scope,
        spec=spec,
        idempotency_key=key,
        reuse_nodes={
            _source_key(index): binding.node
            for index, binding in enumerate(sources, start=1)
        },
    )
    graph.graph_metadata = {
        **(graph.graph_metadata or {}),
        "schema": "36G.local-audio-pipeline.v1",
        "audio_plan_checksum": plan.checksum,
        "audio_pipeline_fingerprint": fingerprint,
        "source_node_ids": list(source_ids),
        "source_count": len(source_ids),
        "waveform_node_key": "waveform",
        "final_node_key": "export",
        "external_requests": 0,
        "external_cost_usd": 0.0,
        "render_status": "planned",
    }
    await session.flush()
    return await _result_for(
        session,
        graph,
        plan=plan,
        source_ids=source_ids,
    )
