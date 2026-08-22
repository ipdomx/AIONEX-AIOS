"""Phase 36G stock-voice AudioPlan to provider speech + local Media DAG bridge."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from aios.audio_factory import AudioPlan
from app.db.models import AudioSpeechExecution, MediaAssetGraph, MediaAssetNode
from app.services.audio_speech_runtime import (
    AudioSpeechExecutionSpec,
    create_audio_speech_execution,
)
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_AUDIO_PROFILE_MAP = {
    "wav-pcm-48k-stereo": "audio-wav-pcm",
    "wav-pcm-48k-mono": "audio-wav-pcm-mono",
    "m4a-aac-48k-stereo": "audio-m4a-aac",
    "webm-opus-48k-stereo": "audio-webm-opus",
}
_INTERNAL_AUDIO_PROFILE = "audio-wav-pcm"
_ALLOWED_PROVIDER = "openai"
_ALLOWED_MODEL = "gpt-4o-mini-tts-2025-12-15"


class AudioSpeechPipelineError(ValueError):
    """A stock-voice AudioPlan cannot safely enter the provider/local DAG."""


@dataclass(frozen=True, slots=True)
class StockSpeechPipelineResult:
    graph_id: str
    graph_checksum: str
    audio_plan_checksum: str
    speech_execution_id: str
    speech_node_id: str
    final_node_id: str
    waveform_node_id: str
    output_profile: str
    estimated_cost_usd: float
    max_cost_usd: float
    provider_requests: int = 0
    provider_spend_usd: float = 0.0

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36G.stock-speech-pipeline.v1",
            "graph_id": self.graph_id,
            "graph_checksum": self.graph_checksum,
            "audio_plan_checksum": self.audio_plan_checksum,
            "speech_execution_id": self.speech_execution_id,
            "output_profile": self.output_profile,
            "estimated_cost_usd": self.estimated_cost_usd,
            "max_cost_usd": self.max_cost_usd,
            "provider_requests": self.provider_requests,
            "provider_spend_usd": self.provider_spend_usd,
            "render_status": "planned",
            "input_text_returned": False,
            "instructions_returned": False,
        }


def _text_for(plan: AudioPlan) -> str:
    if len(plan.segments) != 1:
        raise AudioSpeechPipelineError("stock speech requires exactly one governed segment")
    text = plan.segments[0].text.strip()
    if not 1 <= len(text) <= 4_096:
        raise AudioSpeechPipelineError("stock speech segment is outside the provider input range")
    return text


def _analysis_parameters(plan: AudioPlan) -> dict[str, Any]:
    qa = plan.qa_contract
    return {
        "target_integrated_lufs": qa.target_integrated_lufs,
        "max_true_peak_dbtp": qa.max_true_peak_dbtp,
        "max_loudness_range_lu": qa.max_loudness_range_lu,
        "loudness_tolerance_lu": 1.5,
        "silence_noise_db": -50.0,
        "silence_min_duration_seconds": 0.2,
    }


def build_stock_speech_graph_spec(
    plan: AudioPlan,
    *,
    provider: str,
    model: str,
    voice: str,
    instructions: str,
    speed: float,
    graph_version: int = 1,
) -> MediaGraphSpec:
    """Build provider stock speech followed by the accepted local audio chain."""
    if plan.request.operation not in {"speech", "narration"}:
        raise AudioSpeechPipelineError("stock speech runtime accepts speech or narration only")
    if plan.request.voice_mode != "stock" or plan.request.speaker_count != 1:
        raise AudioSpeechPipelineError("stock speech runtime requires one stock voice")
    if plan.request.source_count != 0:
        raise AudioSpeechPipelineError("stock speech runtime does not accept source audio")
    if plan.request.include_music or plan.request.include_sfx:
        raise AudioSpeechPipelineError("music and generated SFX remain outside stock speech Stage 3")
    if plan.plan_status != "planned" or plan.external_gates:
        raise AudioSpeechPipelineError("stock speech plan still has an external gate")
    if plan.render_status != "not_started":
        raise AudioSpeechPipelineError("stock speech plan render state is not fresh")
    if provider != _ALLOWED_PROVIDER or model != _ALLOWED_MODEL:
        raise AudioSpeechPipelineError("stock speech provider/model is outside the launch gate")
    if len(instructions) > 4_096:
        raise AudioSpeechPipelineError("stock speech instructions are outside the allowed range")
    if not 0.25 <= float(speed) <= 4.0:
        raise AudioSpeechPipelineError("stock speech speed is outside the allowed range")
    text = _text_for(plan)
    output_profile = _AUDIO_PROFILE_MAP.get(plan.output_profile.profile_id)
    if output_profile is None:
        raise AudioSpeechPipelineError("stock speech output profile has no Media mapping")
    analysis = _analysis_parameters(plan)
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    instruction_hash = (
        hashlib.sha256(instructions.encode("utf-8")).hexdigest()
        if instructions
        else None
    )
    nodes = (
        MediaNodeSpec(
            key="speech",
            node_type="provider-speech",
            media_type="audio/wav",
            prompt_metadata={
                "provider": provider,
                "model": model,
                "operation": "synthesize-speech",
                "input_sha256": text_hash,
                "instructions_sha256": instruction_hash,
                "voice": voice,
            },
            rights_metadata={
                "voice_mode": "stock",
                "custom_voice": False,
                "voice_clone": False,
                "voice_transformation": False,
            },
            provenance=(
                {
                    "type": "phase36g-stock-speech-provider-node",
                    "provider": provider,
                    "model": model,
                    "voice": voice,
                    "input_sha256": text_hash,
                    "audio_plan_checksum": plan.checksum,
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
                "highpass_hz": 70,
                "lowpass_hz": 18_000,
                "hardware_adapter": "software",
            },
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
                    "type": "phase36g-stock-speech-local-master",
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
            media_type=plan.output_profile.media_type,
            parameters={
                "operation": "audio_export",
                "output_profile": output_profile,
                "primary_input_index": 0,
                "hardware_adapter": "software",
                **analysis,
            },
            provenance=(
                {
                    "type": "phase36g-stock-speech-final-export",
                    "audio_plan_checksum": plan.checksum,
                },
            ),
        ),
    )
    edges = (
        MediaEdgeSpec("speech", "cleanup", ordinal=0),
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
            "schema": "36G.stock-speech-rights.v1",
            "voice_mode": "stock",
            "custom_voice": False,
            "voice_clone": False,
            "voice_transformation": False,
        },
        provenance=(
            {
                "type": "phase36g-stock-speech-pipeline",
                "audio_plan_checksum": plan.checksum,
                "provider": provider,
                "model": model,
                "voice": voice,
                "input_sha256": text_hash,
            },
        ),
    )


def _pipeline_fingerprint(
    *,
    plan: AudioPlan,
    spec: MediaGraphSpec,
    provider: str,
    model: str,
    voice: str,
    text: str,
    instructions: str,
    speed: float,
    max_duration_seconds: float,
    estimated_cost_usd: float,
    max_cost_usd: float,
) -> str:
    payload = {
        "audio_plan_checksum": plan.checksum,
        "graph_checksum": spec.checksum,
        "provider": provider,
        "model": model,
        "voice": voice,
        "input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "instructions_sha256": (
            hashlib.sha256(instructions.encode("utf-8")).hexdigest()
            if instructions
            else None
        ),
        "speed": round(float(speed), 4),
        "max_duration_seconds": round(float(max_duration_seconds), 3),
        "estimated_cost_usd": round(float(estimated_cost_usd), 9),
        "max_cost_usd": round(float(max_cost_usd), 9),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def _result_for(
    session: AsyncSession,
    *,
    graph: MediaAssetGraph,
    plan: AudioPlan,
    execution: AudioSpeechExecution,
) -> StockSpeechPipelineResult:
    rows = {
        row.logical_key: row
        for row in (
            await session.scalars(
                select(MediaAssetNode).where(MediaAssetNode.graph_id == graph.id)
            )
        ).all()
    }
    speech = rows.get("speech")
    final = rows.get("export")
    waveform = rows.get("waveform")
    if speech is None or final is None or waveform is None:
        raise AudioSpeechPipelineError("stock speech graph is missing required nodes")
    return StockSpeechPipelineResult(
        graph_id=graph.id,
        graph_checksum=graph.graph_checksum,
        audio_plan_checksum=plan.checksum,
        speech_execution_id=execution.id,
        speech_node_id=speech.id,
        final_node_id=final.id,
        waveform_node_id=waveform.id,
        output_profile=graph.output_profile,
        estimated_cost_usd=float(execution.estimated_cost_usd),
        max_cost_usd=float(execution.max_cost_usd),
    )


async def create_stock_speech_pipeline(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    plan: AudioPlan,
    provider: str,
    model: str,
    voice: str,
    instructions: str,
    speed: float,
    max_duration_seconds: float,
    estimated_cost_usd: float,
    max_cost_usd: float,
    idempotency_key: str,
    max_attempts: int = 1,
) -> StockSpeechPipelineResult:
    key = idempotency_key.strip()
    if not 8 <= len(key) <= 160:
        raise AudioSpeechPipelineError("stock speech pipeline idempotency key is invalid")
    text = _text_for(plan)
    spec = build_stock_speech_graph_spec(
        plan,
        provider=provider,
        model=model,
        voice=voice,
        instructions=instructions,
        speed=speed,
    )
    fingerprint = _pipeline_fingerprint(
        plan=plan,
        spec=spec,
        provider=provider,
        model=model,
        voice=voice,
        text=text,
        instructions=instructions,
        speed=speed,
        max_duration_seconds=max_duration_seconds,
        estimated_cost_usd=estimated_cost_usd,
        max_cost_usd=max_cost_usd,
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
            metadata.get("stock_speech_pipeline_fingerprint") != fingerprint
            or metadata.get("audio_plan_checksum") != plan.checksum
        ):
            raise AudioSpeechPipelineError(
                "stock speech idempotency key conflicts with another request"
            )
        execution = await session.scalar(
            select(AudioSpeechExecution).where(
                AudioSpeechExecution.graph_id == existing.id,
                AudioSpeechExecution.organization_id == scope.organization_id,
            )
        )
        if execution is None:
            raise AudioSpeechPipelineError("stock speech execution disappeared")
        return await _result_for(
            session,
            graph=existing,
            plan=plan,
            execution=execution,
        )

    graph = await create_media_graph(
        session,
        scope=scope,
        spec=spec,
        idempotency_key=key,
    )
    speech = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.graph_id == graph.id,
            MediaAssetNode.logical_key == "speech",
        )
    )
    if speech is None:
        raise AudioSpeechPipelineError("stock speech target node was not created")
    execution = await create_audio_speech_execution(
        session,
        spec=AudioSpeechExecutionSpec(
            organization_id=scope.organization_id,
            requested_by_id=scope.created_by_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            studio_job_id=scope.studio_job_id,
            studio_asset_id=scope.studio_asset_id,
            graph_id=graph.id,
            target_node_id=speech.id,
            provider=provider,
            model=model,
            operation="synthesize-speech",
            input_text=text,
            voice=voice,
            instructions=instructions,
            idempotency_key=hashlib.sha256(
                f"{key}:speech".encode("utf-8")
            ).hexdigest(),
            request_options={
                "response_format": "wav",
                "voice": voice,
                "speed": round(float(speed), 4),
                "max_duration_seconds": round(float(max_duration_seconds), 3),
            },
            output_format="wav",
            speed=float(speed),
            max_duration_seconds=float(max_duration_seconds),
            estimated_cost_usd=float(estimated_cost_usd),
            max_cost_usd=float(max_cost_usd),
            max_attempts=int(max_attempts),
        ),
    )
    graph.graph_metadata = {
        **(graph.graph_metadata or {}),
        "schema": "36G.stock-speech-pipeline.v1",
        "audio_plan_checksum": plan.checksum,
        "stock_speech_pipeline_fingerprint": fingerprint,
        "speech_execution_id": execution.id,
        "speech_node_id": speech.id,
        "final_node_key": "export",
        "waveform_node_key": "waveform",
        "provider": provider,
        "model": model,
        "voice": voice,
        "input_sha256": execution.input_sha256,
        "instructions_sha256": execution.instructions_sha256,
        "estimated_cost_usd": float(estimated_cost_usd),
        "max_cost_usd": float(max_cost_usd),
        "provider_requests": 0,
        "provider_spend_usd": 0.0,
        "render_status": "planned",
    }
    await session.flush()
    return await _result_for(
        session,
        graph=graph,
        plan=plan,
        execution=execution,
    )
