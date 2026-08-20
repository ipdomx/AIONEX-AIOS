"""Phase 36F multi-scene video project coordination on top of durable scene authority.

This module never calls a provider. It provides explicit project-level arm/budget gates,
truthful snapshots, and selective failed-scene recovery while preserving historical
VideoExecution rows and the existing provider-job/fencing authority.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.db.models import AuditEvent, MediaAssetGraph, MediaAssetNode, MediaRenderStep, VideoExecution
from app.services.video_runtime import (
    VideoExecutionError,
    VideoExecutionSpec,
    arm_video_execution,
    create_video_execution,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class VideoProjectError(VideoExecutionError):
    """Multi-scene project coordination cannot proceed safely."""


@dataclass(frozen=True, slots=True)
class VideoProjectArmResult:
    graph_id: str
    armed_execution_ids: tuple[str, ...]
    selected_scene_keys: tuple[str, ...]
    projected_cost_usd: float
    max_cost_usd: float


@dataclass(frozen=True, slots=True)
class VideoProjectSceneState:
    scene_key: str
    target_node_id: str
    execution_id: str | None
    status: str
    provider_state: str
    attempts: int
    poll_count: int
    execution_count: int
    estimated_cost_usd: float
    actual_cost_usd: float | None


@dataclass(frozen=True, slots=True)
class VideoProjectSnapshot:
    graph_id: str
    graph_status: str
    status: str
    scenes: tuple[VideoProjectSceneState, ...]
    assembly_node_id: str
    assembly_step_id: str
    assembly_step_status: str
    assembly_ready: bool
    assembly_blocked_by: tuple[str, ...]
    accounted_cost_usd: float
    actual_cost_usd: float


def _latest_executions(rows: list[VideoExecution]) -> dict[str, VideoExecution]:
    latest: dict[str, VideoExecution] = {}
    for row in rows:
        latest[row.target_node_id] = row
    return latest


def _accounted_execution_cost(row: VideoExecution) -> float:
    """Conservative spend/reservation accounting for a durable execution row."""
    estimated = float(row.estimated_cost_usd or 0.0)
    if row.status == "completed":
        return float(row.actual_cost_usd) if row.actual_cost_usd is not None else estimated
    if row.status in {"queued", "running"}:
        return estimated
    if row.status == "failed" and (row.attempts > 0 or row.provider_job_id):
        return float(row.actual_cost_usd) if row.actual_cost_usd is not None else estimated
    return 0.0


def _normalized_scene_keys(scene_keys: tuple[str, ...] | None) -> tuple[str, ...] | None:
    if scene_keys is None:
        return None
    normalized = tuple(str(item).strip() for item in scene_keys)
    if not normalized or any(not item for item in normalized) or len(set(normalized)) != len(normalized):
        raise VideoProjectError("video project scene selection is invalid")
    return normalized


async def arm_video_project(
    session: AsyncSession,
    *,
    organization_id: str,
    graph_id: str,
    max_total_cost_usd: float,
    scene_keys: tuple[str, ...] | None = None,
) -> VideoProjectArmResult:
    """Arm latest planned scene executions only after a conservative whole-project cost gate."""
    cap = float(max_total_cost_usd)
    if cap < 0 or cap > 10_000:
        raise VideoProjectError("video project cost cap is outside the allowed range")
    selected_keys = _normalized_scene_keys(scene_keys)
    graph = await session.scalar(
        select(MediaAssetGraph)
        .where(
            MediaAssetGraph.id == graph_id,
            MediaAssetGraph.organization_id == organization_id,
        )
        .with_for_update()
    )
    if graph is None:
        raise VideoProjectError("video project graph is unavailable")
    rows = list(
        (
            await session.scalars(
                select(VideoExecution)
                .where(
                    VideoExecution.graph_id == graph_id,
                    VideoExecution.organization_id == organization_id,
                )
                .order_by(VideoExecution.created_at, VideoExecution.id)
                .with_for_update()
            )
        ).all()
    )
    if not rows:
        raise VideoProjectError("video project has no provider scene executions")
    latest = _latest_executions(rows)
    by_scene = {row.scene_key: row for row in latest.values()}
    if len(by_scene) != len(latest):
        raise VideoProjectError("video project has ambiguous latest scene identities")
    if selected_keys is None:
        selected = tuple(sorted(by_scene.values(), key=lambda item: (item.created_at, item.id)))
        selected_keys = tuple(row.scene_key for row in selected)
    else:
        missing = tuple(key for key in selected_keys if key not in by_scene)
        if missing:
            raise VideoProjectError("video project scene selection is unavailable")
        selected = tuple(by_scene[key] for key in selected_keys)

    planned: list[VideoExecution] = []
    for row in selected:
        if row.status == "planned":
            planned.append(row)
        elif row.status in {"queued", "running", "completed"}:
            continue
        elif row.status == "failed":
            raise VideoProjectError("failed video scene requires explicit recovery before project arm")
        else:
            raise VideoProjectError("video project scene has unsupported execution state")

    accounted = sum(_accounted_execution_cost(row) for row in rows)
    projected = accounted + sum(float(row.estimated_cost_usd or 0.0) for row in planned)
    if projected > cap + 1e-9:
        raise VideoProjectError("video project cost cap would be exceeded")

    armed: list[str] = []
    for row in planned:
        armed_row = await arm_video_execution(
            session,
            execution_id=row.id,
            organization_id=organization_id,
        )
        armed.append(armed_row.id)
    if armed:
        graph.status = "rendering"
        session.add(
            AuditEvent(
                organization_id=organization_id,
                user_id=planned[0].requested_by_id,
                action="video.project.armed",
                resource_type="media_asset_graph",
                resource_id=graph_id,
                details={
                    "scene_keys": [row.scene_key for row in planned],
                    "armed_count": len(armed),
                    "projected_cost_usd": round(projected, 9),
                    "max_total_cost_usd": round(cap, 9),
                },
            )
        )
    await session.flush()
    return VideoProjectArmResult(
        graph_id=graph_id,
        armed_execution_ids=tuple(armed),
        selected_scene_keys=selected_keys,
        projected_cost_usd=round(projected, 9),
        max_cost_usd=round(cap, 9),
    )


async def create_failed_video_scene_recovery(
    session: AsyncSession,
    *,
    organization_id: str,
    failed_execution_id: str,
    idempotency_key: str,
    max_attempts: int = 1,
) -> VideoExecution:
    """Create a planned replacement for one terminally failed scene; never arm it."""
    key = idempotency_key.strip()
    existing = await session.scalar(
        select(VideoExecution).where(
            VideoExecution.organization_id == organization_id,
            VideoExecution.idempotency_key == key,
        )
    )
    if existing is not None:
        recovery_of = str((existing.request_options or {}).get("recovery_of_execution_id") or "")
        if recovery_of != failed_execution_id:
            raise VideoProjectError("video recovery idempotency key belongs to another execution")
        return existing

    failed = await session.scalar(
        select(VideoExecution)
        .where(
            VideoExecution.id == failed_execution_id,
            VideoExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if failed is None or failed.status != "failed":
        raise VideoProjectError("video recovery requires a terminal failed execution")
    if failed.provider_job_id is None and failed.provider_state == "submitting":
        raise VideoProjectError("ambiguous video submission must be reconciled before recovery")
    if failed.provider_job_id is None and failed.provider_state not in {"not_started", "failed"}:
        raise VideoProjectError("failed video execution is not safe for a new submission")

    target = await session.scalar(
        select(MediaAssetNode)
        .where(
            MediaAssetNode.id == failed.target_node_id,
            MediaAssetNode.graph_id == failed.graph_id,
            MediaAssetNode.organization_id == organization_id,
        )
        .with_for_update()
    )
    if (
        target is None
        or target.status != "planned"
        or target.storage_key
        or target.checksum
    ):
        raise VideoProjectError("failed video scene target is not recoverable")
    target_rows = list(
        (
            await session.scalars(
                select(VideoExecution)
                .where(
                    VideoExecution.organization_id == organization_id,
                    VideoExecution.target_node_id == failed.target_node_id,
                )
                .order_by(VideoExecution.created_at, VideoExecution.id)
                .with_for_update()
            )
        ).all()
    )
    if not target_rows or target_rows[-1].id != failed.id:
        raise VideoProjectError("failed video scene already has a newer execution")

    private = (target.prompt_metadata or {}).get("video_execution")
    if not isinstance(private, dict):
        raise VideoProjectError("failed video scene prompt authority is unavailable")
    prompt = str(private.get("compiled_prompt") or "").strip()
    if not prompt or hashlib.sha256(prompt.encode("utf-8")).hexdigest() != failed.prompt_sha256:
        raise VideoProjectError("failed video scene prompt integrity is invalid")

    options = dict(failed.request_options or {})
    options["recovery_of_execution_id"] = failed.id
    replacement = await create_video_execution(
        session,
        spec=VideoExecutionSpec(
            organization_id=failed.organization_id,
            requested_by_id=failed.requested_by_id,
            workspace_id=failed.workspace_id,
            project_id=failed.project_id,
            studio_job_id=failed.studio_job_id,
            studio_asset_id=failed.studio_asset_id,
            graph_id=failed.graph_id,
            target_node_id=failed.target_node_id,
            scene_key=failed.scene_key,
            provider=failed.provider,
            model=failed.model,
            operation=failed.operation,
            prompt=prompt,
            idempotency_key=key,
            request_options=options,
            output_format=failed.output_format,
            estimated_cost_usd=float(failed.estimated_cost_usd or 0.0),
            max_attempts=max_attempts,
            max_polls=int(failed.max_polls),
        ),
    )
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=failed.requested_by_id,
            action="video.scene.recovery_planned",
            resource_type="video_execution",
            resource_id=replacement.id,
            details={
                "scene_key": failed.scene_key,
                "recovery_of_execution_id": failed.id,
                "provider_job_recorded_on_failed": bool(failed.provider_job_id),
                "estimated_cost_usd": float(failed.estimated_cost_usd or 0.0),
                "max_attempts": max_attempts,
            },
        )
    )
    await session.flush()
    return replacement


async def video_project_snapshot(
    session: AsyncSession,
    *,
    organization_id: str,
    graph_id: str,
) -> VideoProjectSnapshot:
    graph = await session.scalar(
        select(MediaAssetGraph).where(
            MediaAssetGraph.id == graph_id,
            MediaAssetGraph.organization_id == organization_id,
        )
    )
    if graph is None:
        raise VideoProjectError("video project graph is unavailable")
    nodes = list(
        (
            await session.scalars(
                select(MediaAssetNode).where(
                    MediaAssetNode.graph_id == graph_id,
                    MediaAssetNode.organization_id == organization_id,
                )
            )
        ).all()
    )
    provider_nodes = [node for node in nodes if node.node_type == "video-provider-scene"]
    provider_nodes.sort(
        key=lambda node: (
            int((node.timeline_metadata or {}).get("ordinal") or 0),
            node.logical_key,
            node.id,
        )
    )
    assembly_nodes = [node for node in nodes if node.node_type == "assembly"]
    if not provider_nodes or len(assembly_nodes) != 1:
        raise VideoProjectError("video project graph shape is invalid")
    assembly = assembly_nodes[0]
    assembly_steps = list(
        (
            await session.scalars(
                select(MediaRenderStep).where(
                    MediaRenderStep.graph_id == graph_id,
                    MediaRenderStep.target_node_id == assembly.id,
                )
            )
        ).all()
    )
    if len(assembly_steps) != 1:
        raise VideoProjectError("video project assembly authority is invalid")
    assembly_step = assembly_steps[0]
    rows = list(
        (
            await session.scalars(
                select(VideoExecution)
                .where(
                    VideoExecution.graph_id == graph_id,
                    VideoExecution.organization_id == organization_id,
                )
                .order_by(VideoExecution.created_at, VideoExecution.id)
            )
        ).all()
    )
    latest = _latest_executions(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.target_node_id] = counts.get(row.target_node_id, 0) + 1
    scenes: list[VideoProjectSceneState] = []
    for node in provider_nodes:
        snapshot_row = latest.get(node.id)
        scenes.append(
            VideoProjectSceneState(
                scene_key=(snapshot_row.scene_key if snapshot_row is not None else str((node.scene_metadata or {}).get("scene_id") or node.logical_key)),
                target_node_id=node.id,
                execution_id=(snapshot_row.id if snapshot_row is not None else None),
                status=(snapshot_row.status if snapshot_row is not None else "missing"),
                provider_state=(snapshot_row.provider_state if snapshot_row is not None else "missing"),
                attempts=(int(snapshot_row.attempts) if snapshot_row is not None else 0),
                poll_count=(int(snapshot_row.poll_count) if snapshot_row is not None else 0),
                execution_count=counts.get(node.id, 0),
                estimated_cost_usd=(float(snapshot_row.estimated_cost_usd or 0.0) if snapshot_row is not None else 0.0),
                actual_cost_usd=(float(snapshot_row.actual_cost_usd) if snapshot_row is not None and snapshot_row.actual_cost_usd is not None else None),
            )
        )
    blocked = tuple(node.logical_key for node in provider_nodes if node.status != "completed")
    assembly_ready = not blocked and assembly_step.status in {"planned", "retry_queued"}
    if assembly.status == "completed":
        status = "completed"
    elif any(scene.status == "failed" for scene in scenes):
        status = "failed"
    elif assembly_step.status == "running":
        status = "assembling"
    elif not blocked:
        status = "assembly_ready"
    elif any(scene.status in {"queued", "running"} for scene in scenes):
        status = "executing"
    else:
        status = "planned"
    return VideoProjectSnapshot(
        graph_id=graph_id,
        graph_status=graph.status,
        status=status,
        scenes=tuple(scenes),
        assembly_node_id=assembly.id,
        assembly_step_id=assembly_step.id,
        assembly_step_status=assembly_step.status,
        assembly_ready=assembly_ready,
        assembly_blocked_by=blocked,
        accounted_cost_usd=round(sum(_accounted_execution_cost(row) for row in rows), 9),
        actual_cost_usd=round(sum(float(row.actual_cost_usd or 0.0) for row in rows), 9),
    )
