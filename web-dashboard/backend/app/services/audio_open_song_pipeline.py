"""Phase 36G Stage 8 governed full-song Media DAG.

The pipeline persists the private song inputs only inside the tenant-scoped
provider node, exposes hash-only evidence, and creates one dedicated
``AudioSongExecution`` row.  It performs no provider request, model download,
GPU allocation, or balance mutation.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from aios.open_song_factory import (
    ACE_STEP_IMAGE_AMD64_DIGEST,
    ACE_STEP_IMAGE_INDEX_DIGEST,
    ACE_STEP_IMAGE_REPOSITORY,
    DEMUCS_CHECKPOINT_SHA256,
    DEMUCS_MODEL,
    DEMUCS_SOURCE_COMMIT,
    OPEN_SONG_STEMS,
    OpenSongPlan,
    OpenSongRuntimeBinding,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AudioSongExecution, MediaAssetGraph, MediaAssetNode
from app.services.audio_song_runtime import (
    AudioSongExecutionSpec,
    create_audio_song_execution,
)
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec

_OUTPUT_PROFILE = "audio-wav-pcm"
_OUTPUT_MEDIA_TYPE = "audio/wav"
_SHA256_HEX = frozenset("0123456789abcdef")


class AudioOpenSongPipelineError(ValueError):
    """An open-song plan cannot safely enter the durable Media DAG."""


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evidence_hash(value: str, *, label: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(char not in _SHA256_HEX for char in normalized):
        raise AudioOpenSongPipelineError(f"open-song {label} checksum is invalid")
    return normalized


@dataclass(frozen=True, slots=True)
class OpenSongPipelineResult:
    graph_id: str
    graph_checksum: str
    plan_checksum: str
    execution_id: str
    song_node_id: str
    stem_node_ids: dict[str, str]
    mix_node_id: str
    master_node_id: str
    waveform_node_id: str
    final_node_id: str
    route_id: str
    provider: str
    model: str
    model_revision: str
    language_model: str
    language_model_revision: str
    base_container_image_digest: str | None
    endpoint_id_sha256: str | None
    image_sbom_sha256: str | None
    handler_source_sha256: str | None
    container_image_digest: str | None
    max_cost_usd: float
    acceptance_only: bool

    def public_snapshot(self) -> dict[str, Any]:
        return {
            "schema": "36G.open-song-pipeline.v3",
            "graph_id": self.graph_id,
            "graph_checksum": self.graph_checksum,
            "plan_checksum": self.plan_checksum,
            "execution_id": self.execution_id,
            "route_id": self.route_id,
            "provider": self.provider,
            "model": self.model,
            "model_revision": self.model_revision,
            "language_model": self.language_model,
            "language_model_revision": self.language_model_revision,
            "base_container_image_digest": self.base_container_image_digest,
            "endpoint_id_sha256": self.endpoint_id_sha256,
            "image_sbom_sha256": self.image_sbom_sha256,
            "handler_source_sha256": self.handler_source_sha256,
            "container_image_digest": self.container_image_digest,
            "runtime_image_verified": self.container_image_digest is not None,
            "endpoint_id_returned": False,
            "max_cost_usd": self.max_cost_usd,
            "acceptance_only": self.acceptance_only,
            "provider_request_started": False,
            "gpu_job_created": False,
            "render_status": "planned",
            "output_profile": _OUTPUT_PROFILE,
            "stems": list(OPEN_SONG_STEMS),
            "max_attempts": 1,
            "automatic_retry": False,
            "automatic_cross_provider_fallback": False,
            "raw_title_returned": False,
            "raw_concept_returned": False,
            "raw_lyrics_returned": False,
            "known_person_voice": False,
            "voice_clone": False,
            "voice_transformation": False,
            "ai_generated_disclosure_required": True,
            "evidence_separation": {
                "lyrics": True,
                "composition_and_synthetic_vocals": True,
                "stems": list(OPEN_SONG_STEMS),
                "mix": True,
                "master": True,
                "final_audio_qa": True,
            },
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


def build_open_song_graph_spec(
    plan: OpenSongPlan,
    *,
    graph_version: int = 1,
) -> MediaGraphSpec:
    if plan.schema != "36G.open-song-plan.v1":
        raise AudioOpenSongPipelineError("open-song plan schema is unsupported")
    if plan.stems != OPEN_SONG_STEMS:
        raise AudioOpenSongPipelineError("open-song stem contract is incomplete")
    if plan.request.output_profile_id != "wav-pcm-48k-stereo":
        raise AudioOpenSongPipelineError("open-song output profile is unsupported")
    if plan.route.max_attempts != 1:
        raise AudioOpenSongPipelineError("open-song route must permit one attempt")

    request = plan.request
    route = plan.route
    title_sha = _sha256_text(request.title)
    concept_sha = _sha256_text(request.concept)
    lyrics_sha = _sha256_text(request.lyrics)
    analysis = _analysis_parameters()
    rights = {
        **request.rights.public_snapshot(),
        "schema": "36G.open-song-rights.v2",
        "known_person_voice": False,
        "named_person_or_artist_imitation": False,
        "voice_clone": False,
        "voice_transformation": False,
        "synthetic_vocals": True,
        "ai_generated_disclosure_required": True,
    }
    provider_metadata = {
        "schema": "36G.open-song-private-provider-input.v1",
        "route_id": route.route_id,
        "provider": route.provider,
        "model": route.model,
        "model_revision": route.model_revision,
        "language_model": route.language_model,
        "language_model_revision": route.language_model_revision,
        "title": request.title,
        "concept": request.concept,
        "lyrics": request.lyrics,
        "language": request.language,
        "duration_seconds": request.duration_seconds,
        "bpm": request.bpm,
        "musical_key": request.musical_key,
        "time_signature": request.time_signature,
        "seed": request.seed,
        "title_sha256": title_sha,
        "concept_sha256": concept_sha,
        "lyrics_sha256": lyrics_sha,
        "raw_inputs_are_tenant_private": True,
    }

    nodes: list[MediaNodeSpec] = [
        MediaNodeSpec(
            key="song",
            node_type="provider-music",
            media_type=_OUTPUT_MEDIA_TYPE,
            prompt_metadata={"audio_open_song": provider_metadata},
            rights_metadata=rights,
            provenance=(
                {
                    "type": "phase36g-open-song-generation",
                    "route_id": route.route_id,
                    "provider": route.provider,
                    "model": route.model,
                    "model_revision": route.model_revision,
                    "language_model": route.language_model,
                    "language_model_revision": route.language_model_revision,
                    "source_commit": route.source_commit,
                    "base_container_image_index_digest": route.container_image_index_digest,
                    "base_container_image_digest": route.container_image_digest,
                    "plan_checksum": plan.checksum,
                    "title_sha256": title_sha,
                    "concept_sha256": concept_sha,
                    "lyrics_sha256": lyrics_sha,
                    "max_cost_usd": route.max_cost_usd,
                    "acceptance_only": route.acceptance_only,
                    "synthetic_vocals": True,
                    "provider_request_started": False,
                },
            ),
        )
    ]
    for stem in OPEN_SONG_STEMS:
        nodes.append(
            MediaNodeSpec(
                key=f"stem-{stem}",
                node_type="audio-stem",
                media_type=_OUTPUT_MEDIA_TYPE,
                rights_metadata=rights,
                provenance=(
                    {
                        "type": "phase36g-open-song-stem",
                        "stem": stem,
                        "engine": DEMUCS_MODEL,
                        "source_commit": DEMUCS_SOURCE_COMMIT,
                        "checkpoint_sha256": DEMUCS_CHECKPOINT_SHA256,
                        "plan_checksum": plan.checksum,
                    },
                ),
            )
        )
    nodes.extend(
        (
            MediaNodeSpec(
                key="mix",
                node_type="audio-mix",
                media_type=_OUTPUT_MEDIA_TYPE,
                parameters={
                    "operation": "audio_mix",
                    "output_profile": _OUTPUT_PROFILE,
                    "gains_db": [0.0, 0.0, 0.0, 0.0],
                    "hardware_adapter": "software",
                },
                provenance=(
                    {
                        "type": "phase36g-open-song-local-stem-mix",
                        "stems": list(OPEN_SONG_STEMS),
                        "plan_checksum": plan.checksum,
                    },
                ),
            ),
            MediaNodeSpec(
                key="master",
                node_type="audio-master",
                media_type=_OUTPUT_MEDIA_TYPE,
                parameters={
                    "operation": "audio_master",
                    "output_profile": _OUTPUT_PROFILE,
                    "hardware_adapter": "software",
                    **analysis,
                },
                provenance=(
                    {
                        "type": "phase36g-open-song-local-master",
                        "qa_schema": "36G.audio-qa.v1",
                        "plan_checksum": plan.checksum,
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
                media_type=_OUTPUT_MEDIA_TYPE,
                parameters={
                    "operation": "audio_export",
                    "output_profile": _OUTPUT_PROFILE,
                    "primary_input_index": 0,
                    "hardware_adapter": "software",
                    **analysis,
                },
                provenance=(
                    {
                        "type": "phase36g-open-song-final-export",
                        "plan_checksum": plan.checksum,
                        "synthetic_vocal_disclosure_required": True,
                        "ai_generated_disclosure_required": True,
                    },
                ),
            ),
        )
    )

    edges: list[MediaEdgeSpec] = []
    for ordinal, stem in enumerate(OPEN_SONG_STEMS):
        edges.append(
            MediaEdgeSpec(
                parent="song",
                child=f"stem-{stem}",
                dependency_type="derived",
                ordinal=ordinal,
            )
        )
        edges.append(
            MediaEdgeSpec(
                parent=f"stem-{stem}",
                child="mix",
                ordinal=ordinal,
            )
        )
    edges.extend(
        (
            MediaEdgeSpec(parent="mix", child="master", ordinal=0),
            MediaEdgeSpec(parent="master", child="waveform", ordinal=0),
            MediaEdgeSpec(parent="master", child="export", ordinal=0),
            MediaEdgeSpec(
                parent="waveform",
                child="export",
                dependency_type="qa",
                ordinal=1,
            ),
        )
    )
    return MediaGraphSpec(
        title=request.title,
        asset_kind="mixed",
        nodes=tuple(nodes),
        edges=tuple(edges),
        output_profile=_OUTPUT_PROFILE,
        graph_version=graph_version,
        rights_metadata=rights,
        provenance=(
            {
                "type": "phase36g-open-song-pipeline",
                "plan_checksum": plan.checksum,
                "route_id": route.route_id,
                "provider": route.provider,
                "model": route.model,
                "model_revision": route.model_revision,
                "language_model": route.language_model,
                "language_model_revision": route.language_model_revision,
                "source_commit": route.source_commit,
                "container_image_index_digest": route.container_image_index_digest,
                "container_image_digest": route.container_image_digest,
                "max_cost_usd": route.max_cost_usd,
                "acceptance_only": route.acceptance_only,
                "evidence_separation": [
                    "lyrics",
                    "composition-and-synthetic-vocals",
                    "stems",
                    "mix",
                    "master",
                    "final-audio-qa",
                ],
            },
        ),
    )


def _pipeline_fingerprint(
    plan: OpenSongPlan,
    graph_spec: MediaGraphSpec,
    *,
    runtime_evidence_sha256: str,
    pricing_evidence_sha256: str,
    license_evidence_sha256: str,
    runtime_binding: OpenSongRuntimeBinding | None,
) -> str:
    payload = {
        "schema": "36G.open-song-pipeline-fingerprint.v1",
        "plan_checksum": plan.checksum,
        "graph_checksum": graph_spec.checksum,
        "runtime_evidence_sha256": runtime_evidence_sha256,
        "pricing_evidence_sha256": pricing_evidence_sha256,
        "license_evidence_sha256": license_evidence_sha256,
        "route": plan.route.public_snapshot(),
        "runtime_binding": (
            runtime_binding.public_snapshot() if runtime_binding is not None else None
        ),
        "demucs": {
            "model": DEMUCS_MODEL,
            "source_commit": DEMUCS_SOURCE_COMMIT,
            "checkpoint_sha256": DEMUCS_CHECKPOINT_SHA256,
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def _result_for(
    session: AsyncSession,
    *,
    graph: MediaAssetGraph,
    plan: OpenSongPlan,
    execution: AudioSongExecution,
) -> OpenSongPipelineResult:
    nodes = {
        row.logical_key: row
        for row in (
            await session.scalars(
                select(MediaAssetNode).where(MediaAssetNode.graph_id == graph.id)
            )
        ).all()
    }
    required = {
        "song",
        "mix",
        "master",
        "waveform",
        "export",
        *(f"stem-{stem}" for stem in OPEN_SONG_STEMS),
    }
    if not required.issubset(nodes):
        raise AudioOpenSongPipelineError("open-song graph is missing required nodes")
    return OpenSongPipelineResult(
        graph_id=graph.id,
        graph_checksum=graph.graph_checksum,
        plan_checksum=plan.checksum,
        execution_id=execution.id,
        song_node_id=nodes["song"].id,
        stem_node_ids={stem: nodes[f"stem-{stem}"].id for stem in OPEN_SONG_STEMS},
        mix_node_id=nodes["mix"].id,
        master_node_id=nodes["master"].id,
        waveform_node_id=nodes["waveform"].id,
        final_node_id=nodes["export"].id,
        route_id=execution.route_id,
        provider=execution.provider,
        model=execution.model,
        model_revision=execution.model_revision,
        language_model=execution.language_model,
        language_model_revision=execution.language_model_revision,
        base_container_image_digest=execution.base_container_image_digest,
        endpoint_id_sha256=execution.endpoint_id_sha256,
        image_sbom_sha256=execution.image_sbom_sha256,
        handler_source_sha256=execution.handler_source_sha256,
        container_image_digest=execution.container_image_digest,
        max_cost_usd=float(execution.max_cost_usd),
        acceptance_only=execution.route_id == "ace-step-official-space-acceptance",
    )


async def create_open_song_pipeline(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    plan: OpenSongPlan,
    idempotency_key: str,
    runtime_evidence_sha256: str,
    pricing_evidence_sha256: str,
    license_evidence_sha256: str,
    runtime_binding: OpenSongRuntimeBinding | None = None,
) -> OpenSongPipelineResult:
    """Persist one bound but unarmed open-song pipeline without external work."""

    key = idempotency_key.strip()
    if not 8 <= len(key) <= 160:
        raise AudioOpenSongPipelineError("open-song idempotency key is invalid")
    runtime_evidence = _evidence_hash(
        runtime_evidence_sha256, label="runtime evidence"
    )
    pricing_evidence = _evidence_hash(
        pricing_evidence_sha256, label="pricing evidence"
    )
    license_evidence = _evidence_hash(
        license_evidence_sha256, label="license evidence"
    )
    if plan.route.route_id == "runpod-flex-a40":
        if runtime_binding is None or runtime_binding.route_id != plan.route.route_id:
            raise AudioOpenSongPipelineError(
                "RunPod open-song pipeline requires an approved runtime binding"
            )
    elif runtime_binding is not None:
        raise AudioOpenSongPipelineError(
            "acceptance-only open-song route cannot carry a RunPod binding"
        )
    graph_spec = build_open_song_graph_spec(plan)
    fingerprint = _pipeline_fingerprint(
        plan,
        graph_spec,
        runtime_evidence_sha256=runtime_evidence,
        pricing_evidence_sha256=pricing_evidence,
        license_evidence_sha256=license_evidence,
        runtime_binding=runtime_binding,
    )
    existing_graph = await session.scalar(
        select(MediaAssetGraph).where(
            MediaAssetGraph.organization_id == scope.organization_id,
            MediaAssetGraph.idempotency_key == key,
        )
    )
    if existing_graph is not None:
        metadata = dict(existing_graph.graph_metadata or {})
        if metadata.get("open_song_pipeline_fingerprint") != fingerprint:
            raise AudioOpenSongPipelineError(
                "open-song idempotency key conflicts with another plan"
            )
        execution = await session.scalar(
            select(AudioSongExecution).where(
                AudioSongExecution.graph_id == existing_graph.id,
                AudioSongExecution.organization_id == scope.organization_id,
            )
        )
        if execution is None:
            raise AudioOpenSongPipelineError("open-song execution disappeared")
        return await _result_for(
            session,
            graph=existing_graph,
            plan=plan,
            execution=execution,
        )

    graph = await create_media_graph(
        session,
        scope=scope,
        spec=graph_spec,
        idempotency_key=key,
    )
    song_node = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.graph_id == graph.id,
            MediaAssetNode.logical_key == "song",
        )
    )
    if song_node is None:
        raise AudioOpenSongPipelineError("open-song source node was not created")

    request = plan.request
    route = plan.route
    binding = runtime_binding.public_snapshot() if runtime_binding is not None else None
    endpoint_id_sha256 = (
        runtime_binding.endpoint_id_sha256 if runtime_binding is not None else None
    )
    image_sbom_sha256 = (
        runtime_binding.image_sbom_sha256 if runtime_binding is not None else None
    )
    handler_source_sha256 = (
        runtime_binding.handler_source_sha256 if runtime_binding is not None else None
    )
    runtime_image_repository = (
        runtime_binding.container_image_repository
        if runtime_binding is not None
        else None
    )
    runtime_image_index_digest = (
        runtime_binding.container_image_index_digest
        if runtime_binding is not None
        else None
    )
    runtime_image_digest = (
        runtime_binding.container_image_digest if runtime_binding is not None else None
    )
    execution = await create_audio_song_execution(
        session,
        spec=AudioSongExecutionSpec(
            organization_id=scope.organization_id,
            requested_by_id=scope.created_by_id,
            workspace_id=scope.workspace_id,
            project_id=scope.project_id,
            studio_job_id=scope.studio_job_id,
            studio_asset_id=scope.studio_asset_id,
            graph_id=graph.id,
            target_node_id=song_node.id,
            route_id=route.route_id,
            provider=route.provider,
            model=route.model,
            model_revision=route.model_revision,
            language_model=route.language_model,
            language_model_revision=route.language_model_revision,
            source_commit=route.source_commit,
            base_container_image_repository=(
                ACE_STEP_IMAGE_REPOSITORY
                if route.route_id == "runpod-flex-a40"
                else None
            ),
            base_container_image_index_digest=(
                ACE_STEP_IMAGE_INDEX_DIGEST
                if route.route_id == "runpod-flex-a40"
                else None
            ),
            base_container_image_digest=(
                ACE_STEP_IMAGE_AMD64_DIGEST
                if route.route_id == "runpod-flex-a40"
                else None
            ),
            endpoint_id_sha256=endpoint_id_sha256,
            image_sbom_sha256=image_sbom_sha256,
            handler_source_sha256=handler_source_sha256,
            container_image_repository=runtime_image_repository,
            container_image_index_digest=runtime_image_index_digest,
            container_image_digest=runtime_image_digest,
            separation_model=DEMUCS_MODEL,
            separation_revision="v4.0.1",
            separation_source_commit=DEMUCS_SOURCE_COMMIT,
            separation_checkpoint_sha256=DEMUCS_CHECKPOINT_SHA256,
            idempotency_key=hashlib.sha256(
                f"{key}:audio-song".encode("utf-8")
            ).hexdigest(),
            plan_checksum=plan.checksum,
            runtime_evidence_sha256=runtime_evidence,
            pricing_evidence_sha256=pricing_evidence,
            license_evidence_sha256=license_evidence,
            title_sha256=_sha256_text(request.title),
            title_characters=len(request.title),
            concept_sha256=_sha256_text(request.concept),
            concept_characters=len(request.concept),
            lyrics_sha256=_sha256_text(request.lyrics),
            lyrics_characters=len(request.lyrics),
            language=request.language,
            duration_seconds=request.duration_seconds,
            bpm=request.bpm,
            musical_key=request.musical_key,
            time_signature=request.time_signature,
            seed=request.seed,
            output_profile_id=request.output_profile_id,
            rights_basis=request.rights.basis,
            rights_evidence_sha256=request.rights.evidence_sha256,
            commercial_use_authorized=request.rights.commercial_use_authorized,
            provider_terms_accepted=request.rights.provider_terms_accepted,
            ai_generated_disclosure_required=True,
            estimated_cost_usd=route.max_cost_usd,
            max_cost_usd=route.max_cost_usd,
            cost_basis=route.billing_basis,
            rate_usd_per_second=route.rate_usd_per_second,
            max_billed_seconds=route.max_billed_seconds,
            max_attempts=1,
        ),
    )
    graph.graph_metadata = {
        **dict(graph.graph_metadata or {}),
        "schema": "36G.open-song-pipeline.v3",
        "open_song_pipeline_fingerprint": fingerprint,
        "open_song_plan_checksum": plan.checksum,
        "audio_song_execution_id": execution.id,
        "route_id": route.route_id,
        "provider": route.provider,
        "model": route.model,
        "model_revision": route.model_revision,
        "language_model": route.language_model,
        "language_model_revision": route.language_model_revision,
        "source_commit": route.source_commit,
        "base_container_image_repository": (
            ACE_STEP_IMAGE_REPOSITORY
            if route.route_id == "runpod-flex-a40"
            else None
        ),
        "base_container_image_index_digest": (
            ACE_STEP_IMAGE_INDEX_DIGEST
            if route.route_id == "runpod-flex-a40"
            else None
        ),
        "base_container_image_digest": (
            ACE_STEP_IMAGE_AMD64_DIGEST
            if route.route_id == "runpod-flex-a40"
            else None
        ),
        "runtime_binding": binding,
        "runtime_evidence_sha256": runtime_evidence,
        "pricing_evidence_sha256": pricing_evidence,
        "license_evidence_sha256": license_evidence,
        "max_cost_usd": route.max_cost_usd,
        "acceptance_only": route.acceptance_only,
        "provider_request_started": False,
        "gpu_job_created": False,
        "stems": list(OPEN_SONG_STEMS),
        "raw_title_returned": False,
        "raw_concept_returned": False,
        "raw_lyrics_returned": False,
        "known_person_voice": False,
        "voice_clone": False,
        "voice_transformation": False,
        "ai_generated_disclosure_required": True,
    }
    await session.flush()
    return await _result_for(session, graph=graph, plan=plan, execution=execution)
