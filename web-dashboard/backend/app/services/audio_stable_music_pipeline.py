"""Stage 7D Stable Audio 2.5 draft through the governed local audio DAG."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from aios.stable_audio_factory import StableAudioPlan
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AudioMusicExecution, MediaAssetGraph, MediaAssetNode
from app.services.audio_music_runtime import (
    AudioMusicExecutionSpec,
    create_audio_music_execution,
)
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec

_AUDIO_PROFILE_MAP = {
    "wav-pcm-48k-stereo": "audio-wav-pcm",
    "m4a-aac-48k-stereo": "audio-m4a-aac",
    "webm-opus-48k-stereo": "audio-webm-opus",
}
_OUTPUT_MEDIA_TYPES = {
    "wav-pcm-48k-stereo": "audio/wav",
    "m4a-aac-48k-stereo": "audio/mp4",
    "webm-opus-48k-stereo": "audio/webm",
}
_INTERNAL_AUDIO_PROFILE = "audio-wav-pcm"
_EXPECTED_GATES = {
    "valid-funded-stability-credential",
    "stable-audio-2.5-runtime-evidence",
    "music-rights-and-ai-generated-disclosure",
}


class AudioStableMusicPipelineError(ValueError):
    """A StableAudioPlan cannot safely enter the provider/local DAG."""


@dataclass(frozen=True, slots=True)
class StableAudioPipelineResult:
    graph_id: str
    graph_checksum: str
    music_plan_checksum: str
    music_execution_id: str
    music_node_id: str
    final_node_id: str
    waveform_node_id: str
    output_profile: str
    model: str
    fixed_cost_usd: float

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36G.stable-audio-pipeline.v1",
            "graph_id": self.graph_id,
            "graph_checksum": self.graph_checksum,
            "music_plan_checksum": self.music_plan_checksum,
            "music_execution_id": self.music_execution_id,
            "output_profile": self.output_profile,
            "provider": "stability",
            "tier": "draft",
            "model": self.model,
            "preview_model": False,
            "fixed_cost_usd": self.fixed_cost_usd,
            "provider_requests": 0,
            "provider_spend_usd": 0.0,
            "render_status": "planned",
            "raw_prompt_returned": False,
            "raw_lyrics_returned": False,
            "automatic_retry": False,
            "automatic_cross_provider_fallback": False,
            "ai_generated_disclosure_required": True,
            "synthid_disclosure_required": False,
        }


def _analysis_parameters() -> dict[str, Any]:
    return {
        "target_integrated_lufs": -14.0,
        "max_true_peak_dbtp": -1.0,
        "max_loudness_range_lu": 20.0,
        "loudness_tolerance_lu": 1.5,
        "silence_noise_db": -50.0,
        "silence_min_duration_seconds": 0.2,
    }


def build_stable_audio_music_graph_spec(
    plan: StableAudioPlan,
    *,
    graph_version: int = 1,
) -> MediaGraphSpec:
    if plan.render_status != "not_started" or plan.plan_status != "external_gate":
        raise AudioStableMusicPipelineError("Stable Audio render state is not fresh")
    if set(plan.external_gates) != _EXPECTED_GATES:
        raise AudioStableMusicPipelineError("Stable Audio external gates are incomplete")
    if plan.request.output_profile_id not in _AUDIO_PROFILE_MAP:
        raise AudioStableMusicPipelineError("Stable Audio output profile has no Media mapping")
    if (
        plan.route.provider != "stability"
        or plan.route.model != "stable-audio-2.5"
        or plan.route.tier != "draft"
        or plan.route.fixed_cost_usd != 0.20
    ):
        raise AudioStableMusicPipelineError("Stable Audio route is outside Stage 7D")
    prompt_sha = hashlib.sha256(plan.request.prompt.encode("utf-8")).hexdigest()
    analysis = _analysis_parameters()
    output_profile = _AUDIO_PROFILE_MAP[plan.request.output_profile_id]
    nodes = (
        MediaNodeSpec(
            key="music",
            node_type="provider-music",
            media_type="audio/mpeg",
            prompt_metadata={
                "provider": "stability",
                "model": "stable-audio-2.5",
                "operation": "generate-music",
                "tier": "draft",
                "prompt_sha256": prompt_sha,
                "instrumental_only": True,
            },
            rights_metadata={
                **plan.request.rights.public_snapshot(),
                "named_artist_imitation": False,
                "preview_model": False,
                "synthid_disclosure_required": False,
                "ai_generated_disclosure_required": True,
                "reuse_same_user_plan": True,
                "cost_policy": plan.cost_policy.public_snapshot(),
            },
            provenance=(
                {
                    "type": "phase36g-stable-audio-provider-node",
                    "provider": "stability",
                    "model": "stable-audio-2.5",
                    "tier": "draft",
                    "prompt_sha256": prompt_sha,
                    "music_plan_checksum": plan.checksum,
                    "fixed_cost_usd": 0.20,
                },
            ),
        ),
        MediaNodeSpec(
            key="cleanup",
            node_type="audio-cleanup",
            media_type="audio/wav",
            parameters={
                "operation": "audio_cleanup",
                "output_profile": _INTERNAL_AUDIO_PROFILE,
                "highpass_hz": 35,
                "lowpass_hz": 20_000,
                "hardware_adapter": "software",
            },
            provenance=(
                {
                    "type": "phase36g-stable-audio-local-cleanup",
                    "music_plan_checksum": plan.checksum,
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
                **analysis,
            },
            provenance=(
                {
                    "type": "phase36g-stable-audio-local-master",
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
                "hardware_adapter": "software",
            },
        ),
        MediaNodeSpec(
            key="export",
            node_type="audio-export",
            media_type=_OUTPUT_MEDIA_TYPES[plan.request.output_profile_id],
            parameters={
                "operation": "audio_export",
                "output_profile": output_profile,
                "primary_input_index": 0,
                "hardware_adapter": "software",
                **analysis,
            },
            provenance=(
                {
                    "type": "phase36g-stable-audio-final-export",
                    "music_plan_checksum": plan.checksum,
                    "preview_model": False,
                    "synthid_disclosure_required": False,
                    "ai_generated_disclosure_required": True,
                },
            ),
        ),
    )
    edges = (
        MediaEdgeSpec("music", "cleanup", ordinal=0),
        MediaEdgeSpec("cleanup", "master", ordinal=0),
        MediaEdgeSpec("master", "waveform", ordinal=0),
        MediaEdgeSpec("master", "export", ordinal=0),
        MediaEdgeSpec("waveform", "export", dependency_type="qa", ordinal=1),
    )
    return MediaGraphSpec(
        title=plan.request.title,
        asset_kind="mixed",
        nodes=nodes,
        edges=edges,
        output_profile=output_profile,
        graph_version=graph_version,
        rights_metadata={
            "schema": "36G.stable-audio-rights.v1",
            **plan.request.rights.public_snapshot(),
            "instrumental_only": True,
            "named_artist_imitation": False,
            "preview_model": False,
            "synthid_disclosure_required": False,
            "ai_generated_disclosure_required": True,
        },
        provenance=(
            {
                "type": "phase36g-stable-audio-music-pipeline",
                "music_plan_checksum": plan.checksum,
                "provider": "stability",
                "model": "stable-audio-2.5",
                "tier": "draft",
                "fixed_cost_usd": 0.20,
            },
        ),
    )


def _pipeline_fingerprint(
    plan: StableAudioPlan,
    spec: MediaGraphSpec,
    *,
    runtime_evidence_sha256: str,
    pricing_evidence_sha256: str,
) -> str:
    payload = {
        "music_plan_checksum": plan.checksum,
        "graph_checksum": spec.checksum,
        "provider": "stability",
        "model": "stable-audio-2.5",
        "tier": "draft",
        "fixed_cost_usd": 0.20,
        "output_profile": plan.request.output_profile_id,
        "runtime_evidence_sha256": runtime_evidence_sha256,
        "pricing_evidence_sha256": pricing_evidence_sha256,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def _result_for(
    session: AsyncSession,
    *,
    graph: MediaAssetGraph,
    plan: StableAudioPlan,
    execution: AudioMusicExecution,
) -> StableAudioPipelineResult:
    rows = {
        row.logical_key: row
        for row in (
            await session.scalars(
                select(MediaAssetNode).where(MediaAssetNode.graph_id == graph.id)
            )
        ).all()
    }
    music = rows.get("music")
    final = rows.get("export")
    waveform = rows.get("waveform")
    if music is None or final is None or waveform is None:
        raise AudioStableMusicPipelineError("Stable Audio graph is missing required nodes")
    return StableAudioPipelineResult(
        graph_id=graph.id,
        graph_checksum=graph.graph_checksum,
        music_plan_checksum=plan.checksum,
        music_execution_id=execution.id,
        music_node_id=music.id,
        final_node_id=final.id,
        waveform_node_id=waveform.id,
        output_profile=graph.output_profile,
        model=execution.model,
        fixed_cost_usd=float(execution.max_cost_usd),
    )


async def create_stable_audio_music_pipeline(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    plan: StableAudioPlan,
    idempotency_key: str,
    runtime_evidence_sha256: str,
    pricing_evidence_sha256: str,
) -> StableAudioPipelineResult:
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 160:
        raise AudioStableMusicPipelineError("Stable Audio idempotency key is invalid")
    for label, value in (
        ("runtime evidence", runtime_evidence_sha256),
        ("pricing evidence", pricing_evidence_sha256),
    ):
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise AudioStableMusicPipelineError(f"Stable Audio {label} checksum is invalid")

    spec = build_stable_audio_music_graph_spec(plan)
    fingerprint = _pipeline_fingerprint(
        plan,
        spec,
        runtime_evidence_sha256=runtime_evidence_sha256,
        pricing_evidence_sha256=pricing_evidence_sha256,
    )
    existing = await session.scalar(
        select(MediaAssetGraph).where(
            MediaAssetGraph.organization_id == scope.organization_id,
            MediaAssetGraph.idempotency_key == key,
        )
    )
    if existing is not None:
        metadata = existing.graph_metadata or {}
        if (
            metadata.get("stable_audio_pipeline_fingerprint") != fingerprint
            or metadata.get("music_plan_checksum") != plan.checksum
        ):
            raise AudioStableMusicPipelineError("Stable Audio idempotency key conflicts with another plan")
        execution = await session.scalar(
            select(AudioMusicExecution).where(
                AudioMusicExecution.graph_id == existing.id,
                AudioMusicExecution.organization_id == scope.organization_id,
            )
        )
        if execution is None:
            raise AudioStableMusicPipelineError("Stable Audio execution disappeared")
        return await _result_for(session, graph=existing, plan=plan, execution=execution)

    reusable_execution = await session.scalar(
        select(AudioMusicExecution)
        .where(
            AudioMusicExecution.organization_id == scope.organization_id,
            AudioMusicExecution.requested_by_id == scope.created_by_id,
            AudioMusicExecution.plan_checksum == plan.checksum,
            AudioMusicExecution.runtime_evidence_sha256 == runtime_evidence_sha256,
            AudioMusicExecution.pricing_evidence_sha256 == pricing_evidence_sha256,
            AudioMusicExecution.provider == "stability",
            AudioMusicExecution.model == "stable-audio-2.5",
            AudioMusicExecution.tier == "draft",
            AudioMusicExecution.status.in_(("planned", "queued", "running", "completed")),
            AudioMusicExecution.provider_state.in_(("not_started", "submitting", "completed")),
        )
        .order_by(AudioMusicExecution.created_at, AudioMusicExecution.id)
        .limit(1)
    )
    if reusable_execution is not None:
        reusable_graph = await session.get(MediaAssetGraph, reusable_execution.graph_id)
        if reusable_graph is None:
            raise AudioStableMusicPipelineError("reusable Stable Audio graph disappeared")
        return await _result_for(
            session,
            graph=reusable_graph,
            plan=plan,
            execution=reusable_execution,
        )

    graph = await create_media_graph(
        session,
        scope=scope,
        spec=spec,
        idempotency_key=key,
    )
    music = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.graph_id == graph.id,
            MediaAssetNode.logical_key == "music",
        )
    )
    if music is None:
        raise AudioStableMusicPipelineError("Stable Audio provider node was not created")

    execution = await create_audio_music_execution(
        session,
        spec=AudioMusicExecutionSpec(
            organization_id=scope.organization_id,
            requested_by_id=scope.created_by_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            studio_job_id=scope.studio_job_id,
            studio_asset_id=scope.studio_asset_id,
            graph_id=graph.id,
            target_node_id=music.id,
            plan_checksum=plan.checksum,
            runtime_evidence_sha256=runtime_evidence_sha256,
            pricing_evidence_sha256=pricing_evidence_sha256,
            prompt=plan.request.prompt,
            lyrics="",
            instrumental_only=True,
            rights_basis="instrumental",
            rights_evidence_sha256=None,
            tier="draft",
            provider="stability",
            model="stable-audio-2.5",
            idempotency_key=hashlib.sha256(f"{key}:music".encode("utf-8")).hexdigest(),
            request_options={
                "output_format": "mp3",
                "preview_model": False,
                "nominal_duration_seconds": 30,
                "synthid_disclosure_required": False,
                "ai_generated_disclosure_required": True,
                "reuse_same_user_plan": True,
                "cost_policy": plan.cost_policy.public_snapshot(),
            },
            final_generation_approved=False,
            final_approval_evidence_sha256=None,
            prior_draft_checksum=None,
            estimated_cost_usd=0.20,
            max_cost_usd=0.20,
            preview_model=False,
            synthid_disclosure_required=False,
            ai_generated_disclosure_required=True,
        ),
    )
    graph.graph_metadata = {
        **(graph.graph_metadata or {}),
        "schema": "36G.stable-audio-pipeline.v1",
        "music_plan_checksum": plan.checksum,
        "stable_audio_pipeline_fingerprint": fingerprint,
        "music_execution_id": execution.id,
        "provider": "stability",
        "tier": "draft",
        "model": "stable-audio-2.5",
        "fixed_cost_usd": 0.20,
        "runtime_evidence_sha256": runtime_evidence_sha256,
        "pricing_evidence_sha256": pricing_evidence_sha256,
        "preview_model": False,
        "synthid_disclosure_required": False,
        "ai_generated_disclosure_required": True,
        "reuse_same_user_plan": True,
    }
    await session.flush()
    return await _result_for(session, graph=graph, plan=plan, execution=execution)
