"""Phase 36F governed VideoPlan -> Media DAG -> planned VideoExecution pipeline."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from aios.video_factory import (
    VideoFactoryError,
    VideoRequest,
    VideoRuntimeEvidence,
    build_video_plan_for_provider,
    runtime_ready_provider,
)
from app.db.models import MediaAssetNode
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec
from app.services.video_providers import ProviderVideoRequest, openai_sora_fixed_cost
from app.services.video_runtime import VideoExecutionSpec, create_video_execution
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


_VIDEO_REFERENCE_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_REFERENCE_OPERATIONS = frozenset({"image-to-video", "logo-to-video", "reference-to-video"})


class VideoPipelineError(RuntimeError):
    """A live-routable VideoPlan cannot be materialized safely."""


@dataclass(frozen=True, slots=True)
class RoutedVideoPipeline:
    graph_id: str
    execution_ids: tuple[str, ...]
    scene_node_ids: tuple[str, ...]
    assembly_node_id: str
    provider: str
    model: str
    video_plan_checksum: str
    continuity_id: str
    estimated_cost_usd: float
    reference_node_id: str | None = None


async def _load_video_reference_input(
    session: AsyncSession, *, organization_id: str, node_id: str
) -> MediaAssetNode:
    row = await session.scalar(
        select(MediaAssetNode).where(
            MediaAssetNode.id == node_id,
            MediaAssetNode.organization_id == organization_id,
        )
    )
    if (
        row is None
        or row.status != "completed"
        or not row.storage_key
        or not row.checksum
        or not row.media_type
        or row.media_type not in _VIDEO_REFERENCE_CONTENT_TYPES
        or not row.size_bytes
        or row.size_bytes <= 0
        or row.size_bytes > 20 * 1024 * 1024
    ):
        raise VideoPipelineError("video reference input is unavailable")
    return row


async def create_routed_video_pipeline(
    session: AsyncSession,
    *,
    scope: MediaGraphScope,
    request: VideoRequest,
    runtime_evidence: tuple[VideoRuntimeEvidence, ...],
    idempotency_key: str,
    reference_node_id: str | None = None,
) -> RoutedVideoPipeline:
    """Create planned provider scene executions; never arm/spend."""
    reference_id = str(reference_node_id or "").strip() or None
    reference_source: MediaAssetNode | None = None
    if request.operation == "text-to-video":
        if request.reference_count != 0 or reference_id is not None:
            raise VideoPipelineError("text-to-video pipeline cannot carry a reference input")
    elif request.operation in _REFERENCE_OPERATIONS:
        if request.reference_count != 1 or reference_id is None:
            raise VideoPipelineError("reference video pipeline requires exactly one governed input")
        reference_source = await _load_video_reference_input(
            session, organization_id=scope.organization_id, node_id=reference_id
        )
    else:
        raise VideoPipelineError("Stage 36F3B pipeline operation is not yet accepted")
    try:
        route = runtime_ready_provider(request, evidence=runtime_evidence)
    except VideoFactoryError as exc:
        raise VideoPipelineError(str(exc)) from exc
    if route.provider != "openai" or route.model not in {"sora-2", "sora-2-pro"}:
        raise VideoPipelineError("Stage 36F2B worker has no accepted adapter for the selected provider")
    try:
        plan = build_video_plan_for_provider(request, provider=route.provider, model=route.model)
    except VideoFactoryError as exc:
        raise VideoPipelineError(str(exc)) from exc

    scene_specs: list[MediaNodeSpec] = []
    total_estimated = 0.0
    scene_costs: dict[str, float] = {}
    for scene, compiled in zip(plan.scenes, plan.compiled_scenes, strict=True):
        size = str(compiled.settings.get("size") or "")
        seconds = int(compiled.settings.get("seconds") or scene.duration_seconds)
        try:
            estimated, _ = openai_sora_fixed_cost(
                ProviderVideoRequest(
                    provider=route.provider,
                    model=route.model,
                    operation=request.operation,
                    prompt=compiled.prompt,
                    seconds=seconds,
                    size=size,
                )
            )
        except Exception as exc:
            raise VideoPipelineError("video provider pricing evidence is unavailable for the selected route") from exc
        scene_costs[scene.scene_id] = estimated
        total_estimated += estimated
        scene_specs.append(
            MediaNodeSpec(
                key=f"provider-{scene.scene_id}",
                node_type="video-provider-scene",
                media_type="video/mp4",
                prompt_metadata={
                    "video_plan_checksum": plan.checksum,
                    "continuity_id": plan.continuity_id,
                    "scene_id": scene.scene_id,
                },
                parameters={
                    "executor": "video-provider",
                    "provider": route.provider,
                    "model": route.model,
                    "provider_operation": request.operation,
                    # Intentionally no `operation`: Phase36D FFmpeg must never claim provider scenes.
                },
                scene_metadata={
                    "scene_id": scene.scene_id,
                    "purpose": scene.purpose,
                    "transition": scene.transition,
                    "continuity_id": plan.continuity_id,
                },
                timeline_metadata={
                    "duration_seconds": scene.duration_seconds,
                    "ordinal": len(scene_specs),
                },
            )
        )
    reference_spec: MediaNodeSpec | None = None
    reusable_nodes: dict[str, MediaAssetNode] = {}
    if reference_source is not None:
        reference_spec = MediaNodeSpec(
            key="reference-00",
            node_type="image",
            media_type=reference_source.media_type,
            provenance=(
                {
                    "type": "phase36f-governed-video-reference",
                    "source_node_id": reference_source.id,
                    "checksum": reference_source.checksum,
                },
            ),
        )
        reusable_nodes["reference-00"] = reference_source

    assembly = MediaNodeSpec(
        key="assembly",
        node_type="assembly",
        media_type="video/mp4",
        parameters={
            "operation": "assemble",
            "output_profile": "video-mp4-h264",
            "hardware_adapter": "software",
        },
        scene_metadata={"continuity_id": plan.continuity_id},
        timeline_metadata={"scene_count": len(scene_specs)},
    )
    edges_list = [
        MediaEdgeSpec(node.key, "assembly", ordinal=index)
        for index, node in enumerate(scene_specs)
    ]
    if reference_spec is not None:
        edges_list.extend(
            MediaEdgeSpec("reference-00", node.key, ordinal=index)
            for index, node in enumerate(scene_specs)
        )
    graph_nodes = [*([reference_spec] if reference_spec is not None else []), *scene_specs, assembly]
    graph_spec = MediaGraphSpec(
        title=request.title,
        asset_kind="video",
        nodes=tuple(graph_nodes),
        edges=tuple(edges_list),
        output_profile="video-mp4-h264",
        provenance=(
            {
                "type": "phase36f-routed-video-plan",
                "video_plan_checksum": plan.checksum,
                "continuity_id": plan.continuity_id,
                "provider": route.provider,
                "model": route.model,
                "render_status": "planned",
                "reference_count": request.reference_count,
            },
        ),
    )
    reference_fingerprint = (
        f"{reference_source.id}:{reference_source.checksum}" if reference_source is not None else "none"
    )
    fingerprint = hashlib.sha256(
        f"{scope.organization_id}:{idempotency_key}:{plan.checksum}:{route.provider}:{route.model}:{reference_fingerprint}".encode()
    ).hexdigest()
    graph = await create_media_graph(
        session,
        scope=scope,
        spec=graph_spec,
        idempotency_key=f"p36f-graph-{fingerprint[:48]}",
        reuse_nodes=reusable_nodes,
    )
    nodes = list(
        (
            await session.scalars(
                select(MediaAssetNode)
                .where(MediaAssetNode.graph_id == graph.id)
                .order_by(MediaAssetNode.logical_key)
            )
        ).all()
    )
    by_key = {row.logical_key: row for row in nodes}
    assembly_row = by_key.get("assembly")
    if assembly_row is None:
        raise VideoPipelineError("video assembly node was not materialized")

    execution_ids: list[str] = []
    scene_node_ids: list[str] = []
    for scene, compiled in zip(plan.scenes, plan.compiled_scenes, strict=True):
        node = by_key.get(f"provider-{scene.scene_id}")
        if node is None:
            raise VideoPipelineError("video provider scene node was not materialized")
        settings = dict(compiled.settings)
        settings["reference_count"] = request.reference_count
        execution = await create_video_execution(
            session,
            spec=VideoExecutionSpec(
                organization_id=scope.organization_id,
                requested_by_id=scope.created_by_id,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                studio_job_id=scope.studio_job_id,
                studio_asset_id=scope.studio_asset_id,
                graph_id=graph.id,
                target_node_id=node.id,
                scene_key=scene.scene_id,
                provider=route.provider,
                model=route.model,
                operation=request.operation,
                prompt=compiled.prompt,
                idempotency_key=f"p36f-video-{fingerprint[:40]}-{scene.scene_id}",
                request_options=settings,
                output_format="mp4",
                estimated_cost_usd=scene_costs[scene.scene_id],
                max_attempts=3,
                max_polls=360,
            ),
        )
        execution_ids.append(execution.id)
        scene_node_ids.append(node.id)
    await session.flush()
    return RoutedVideoPipeline(
        graph_id=graph.id,
        execution_ids=tuple(execution_ids),
        scene_node_ids=tuple(scene_node_ids),
        assembly_node_id=assembly_row.id,
        provider=route.provider,
        model=route.model,
        video_plan_checksum=plan.checksum,
        continuity_id=plan.continuity_id,
        estimated_cost_usd=round(total_estimated, 9),
        reference_node_id=(by_key["reference-00"].id if reference_source is not None else None),
    )
