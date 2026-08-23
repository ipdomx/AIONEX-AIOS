"""Stage 7 Lyria 3 MusicPlan through Replicate to the local FFmpeg Media DAG."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from aios.music_factory import MusicPlan
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
    "valid-replicate-credential",
    "lyria-preview-runtime-evidence",
    "music-rights-and-synthid-disclosure",
}


class AudioMusicPipelineError(ValueError):
    """A MusicPlan cannot safely enter the provider/local DAG."""


@dataclass(frozen=True, slots=True)
class MusicPipelineResult:
    graph_id: str
    graph_checksum: str
    music_plan_checksum: str
    music_execution_id: str
    music_node_id: str
    final_node_id: str
    waveform_node_id: str
    output_profile: str
    tier: str
    model: str
    fixed_cost_usd: float
    provider_requests: int = 0
    provider_spend_usd: float = 0.0

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36G.lyria-music-pipeline.v1",
            "graph_id": self.graph_id,
            "graph_checksum": self.graph_checksum,
            "music_plan_checksum": self.music_plan_checksum,
            "music_execution_id": self.music_execution_id,
            "output_profile": self.output_profile,
            "tier": self.tier,
            "model": self.model,
            "preview_model": True,
            "fixed_cost_usd": self.fixed_cost_usd,
            "default_low_cost_route": self.tier == "draft",
            "provider_requests": self.provider_requests,
            "provider_spend_usd": self.provider_spend_usd,
            "render_status": "planned",
            "raw_prompt_returned": False,
            "raw_lyrics_returned": False,
            "automatic_retry": False,
        }


def _analysis_parameters(plan: MusicPlan) -> dict[str, Any]:
    return {
        "target_integrated_lufs": -14.0,
        "max_true_peak_dbtp": -1.0,
        "max_loudness_range_lu": 20.0,
        "loudness_tolerance_lu": 1.5,
        "silence_noise_db": -50.0,
        "silence_min_duration_seconds": 0.2,
    }


def build_lyria_music_graph_spec(
    plan: MusicPlan,
    *,
    graph_version: int = 1,
) -> MediaGraphSpec:
    if plan.render_status != "not_started":
        raise AudioMusicPipelineError("music render state is not fresh")
    if set(plan.external_gates) != _EXPECTED_GATES:
        raise AudioMusicPipelineError("music external gates are incomplete")
    if plan.request.output_profile_id not in _AUDIO_PROFILE_MAP:
        raise AudioMusicPipelineError("music output profile has no Media mapping")
    if plan.route.model not in {"lyria-3-clip-preview", "lyria-3-pro-preview"}:
        raise AudioMusicPipelineError("music model is outside the Lyria launch route")
    prompt_sha = hashlib.sha256(plan.request.prompt.encode("utf-8")).hexdigest()
    lyrics_sha = (
        hashlib.sha256(plan.request.lyrics.encode("utf-8")).hexdigest()
        if plan.request.lyrics
        else None
    )
    analysis = _analysis_parameters(plan)
    output_profile = _AUDIO_PROFILE_MAP[plan.request.output_profile_id]
    nodes = (
        MediaNodeSpec(
            key="music",
            node_type="provider-music",
            media_type="audio/mpeg",
            prompt_metadata={
                "provider": "replicate",
                "model": plan.route.model,
                "operation": "generate-music",
                "tier": plan.route.tier,
                "prompt_sha256": prompt_sha,
                "lyrics_sha256": lyrics_sha,
                "instrumental_only": plan.request.instrumental_only,
            },
            rights_metadata={
                **plan.request.rights.public_snapshot(),
                "named_artist_imitation": False,
                "preview_model": True,
                "synthid_disclosure_required": True,
                "reuse_same_user_plan": True,
                "cost_policy": plan.cost_policy.public_snapshot(),
            },
            provenance=(
                {
                    "type": "phase36g-lyria-provider-node",
                    "provider": "replicate",
                    "model": plan.route.model,
                    "tier": plan.route.tier,
                    "prompt_sha256": prompt_sha,
                    "lyrics_sha256": lyrics_sha,
                    "music_plan_checksum": plan.checksum,
                    "fixed_cost_usd": plan.route.fixed_cost_usd,
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
                    "type": "phase36g-lyria-local-cleanup",
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
                    "type": "phase36g-lyria-local-master",
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
                    "type": "phase36g-lyria-final-export",
                    "music_plan_checksum": plan.checksum,
                    "preview_model": True,
                    "synthid_disclosure_required": True,
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
            "schema": "36G.lyria-music-rights.v1",
            **plan.request.rights.public_snapshot(),
            "instrumental_only": plan.request.instrumental_only,
            "named_artist_imitation": False,
            "preview_model": True,
            "synthid_disclosure_required": True,
        },
        provenance=(
            {
                "type": "phase36g-lyria-music-pipeline",
                "music_plan_checksum": plan.checksum,
                "provider": "replicate",
                "model": plan.route.model,
                "tier": plan.route.tier,
                "fixed_cost_usd": plan.route.fixed_cost_usd,
                "default_low_cost_route": plan.route.tier == "draft",
            },
        ),
    )


def _pipeline_fingerprint(
    plan: MusicPlan,
    spec: MediaGraphSpec,
    *,
    runtime_evidence_sha256: str,
    pricing_evidence_sha256: str,
) -> str:
    payload = {
        "music_plan_checksum": plan.checksum,
        "graph_checksum": spec.checksum,
        "provider": "replicate",
        "model": plan.route.model,
        "tier": plan.route.tier,
        "fixed_cost_usd": plan.route.fixed_cost_usd,
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
    plan: MusicPlan,
    execution: AudioMusicExecution,
) -> MusicPipelineResult:
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
        raise AudioMusicPipelineError("music graph is missing required nodes")
    return MusicPipelineResult(
        graph_id=graph.id,
        graph_checksum=graph.graph_checksum,
        music_plan_checksum=plan.checksum,
        music_execution_id=execution.id,
        music_node_id=music.id,
        final_node_id=final.id,
        waveform_node_id=waveform.id,
        output_profile=graph.output_profile,
        tier=execution.tier,
        model=execution.model,
        fixed_cost_usd=float(execution.max_cost_usd),
    )


async def create_lyria_music_pipeline(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    plan: MusicPlan,
    idempotency_key: str,
    runtime_evidence_sha256: str,
    pricing_evidence_sha256: str,
) -> MusicPipelineResult:
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 160:
        raise AudioMusicPipelineError("music pipeline idempotency key is invalid")
    for label, value in (
        ("runtime evidence", runtime_evidence_sha256),
        ("pricing evidence", pricing_evidence_sha256),
    ):
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise AudioMusicPipelineError(f"music {label} checksum is invalid")
    spec = build_lyria_music_graph_spec(plan)
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
            metadata.get("music_pipeline_fingerprint") != fingerprint
            or metadata.get("music_plan_checksum") != plan.checksum
        ):
            raise AudioMusicPipelineError("music idempotency key conflicts with another plan")
        execution = await session.scalar(
            select(AudioMusicExecution).where(
                AudioMusicExecution.graph_id == existing.id,
                AudioMusicExecution.organization_id == scope.organization_id,
            )
        )
        if execution is None:
            raise AudioMusicPipelineError("music execution disappeared")
        return await _result_for(session, graph=existing, plan=plan, execution=execution)

    if plan.route.tier == "final":
        completed_draft = await session.scalar(
            select(AudioMusicExecution)
            .where(
                AudioMusicExecution.organization_id == scope.organization_id,
                AudioMusicExecution.requested_by_id == scope.created_by_id,
                AudioMusicExecution.tier == "draft",
                AudioMusicExecution.status == "completed",
                AudioMusicExecution.output_checksum
                == plan.request.prior_draft_checksum,
            )
            .order_by(AudioMusicExecution.completed_at.desc())
            .limit(1)
        )
        if completed_draft is None:
            raise AudioMusicPipelineError(
                "final music requires a completed governed draft from the same user"
            )

    reusable_execution = await session.scalar(
        select(AudioMusicExecution)
        .where(
            AudioMusicExecution.organization_id == scope.organization_id,
            AudioMusicExecution.requested_by_id == scope.created_by_id,
            AudioMusicExecution.plan_checksum == plan.checksum,
            AudioMusicExecution.runtime_evidence_sha256
            == runtime_evidence_sha256,
            AudioMusicExecution.pricing_evidence_sha256
            == pricing_evidence_sha256,
            AudioMusicExecution.provider == "replicate",
            AudioMusicExecution.model == plan.route.model,
            AudioMusicExecution.tier == plan.route.tier,
            AudioMusicExecution.status.in_(
                ("planned", "queued", "running", "completed")
            ),
            AudioMusicExecution.provider_state.in_(
                ("not_started", "submitting", "submitted", "completed")
            ),
        )
        .order_by(AudioMusicExecution.created_at, AudioMusicExecution.id)
        .limit(1)
    )
    if reusable_execution is not None:
        reusable_graph = await session.get(
            MediaAssetGraph, reusable_execution.graph_id
        )
        if reusable_graph is None:
            raise AudioMusicPipelineError("reusable music graph disappeared")
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
        raise AudioMusicPipelineError("music provider node was not created")
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
            lyrics=plan.request.lyrics,
            instrumental_only=plan.request.instrumental_only,
            rights_basis=plan.request.rights.basis,
            rights_evidence_sha256=plan.request.rights.evidence_sha256,
            tier=plan.route.tier,
            provider="replicate",
            model=plan.route.model,
            idempotency_key=hashlib.sha256(f"{key}:music".encode("utf-8")).hexdigest(),
            request_options={
                "output_format": "mp3",
                "preview_model": True,
                "nominal_duration_seconds": plan.route.nominal_duration_seconds,
                "synthid_disclosure_required": True,
                "reuse_same_user_plan": True,
                "cost_policy": plan.cost_policy.public_snapshot(),
            },
            final_generation_approved=plan.request.final_generation_approved,
            final_approval_evidence_sha256=(
                plan.request.final_approval_evidence_sha256
            ),
            prior_draft_checksum=plan.request.prior_draft_checksum,
            estimated_cost_usd=plan.route.fixed_cost_usd,
            max_cost_usd=plan.route.fixed_cost_usd,
        ),
    )
    graph.graph_metadata = {
        **(graph.graph_metadata or {}),
        "schema": "36G.lyria-music-pipeline.v1",
        "music_plan_checksum": plan.checksum,
        "music_pipeline_fingerprint": fingerprint,
        "music_execution_id": execution.id,
        "tier": plan.route.tier,
        "model": plan.route.model,
        "fixed_cost_usd": plan.route.fixed_cost_usd,
        "runtime_evidence_sha256": runtime_evidence_sha256,
        "pricing_evidence_sha256": pricing_evidence_sha256,
        "preview_model": True,
        "default_low_cost_route": plan.route.tier == "draft",
        "reuse_same_user_plan": True,
    }
    await session.flush()
    return await _result_for(session, graph=graph, plan=plan, execution=execution)
