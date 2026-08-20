"""Phase 36F durable multi-scene video execution authority (no provider HTTP transport)."""
from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from aios.video_factory import VIDEO_PROVIDER_CAPABILITIES, VideoPlan
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    MediaAssetGraph,
    MediaAssetNode,
    VideoExecution,
    VideoSceneExecution,
    uuid_str,
)
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec
from app.services.media_storage import MediaObjectStore, media_object_store
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
_ALLOWED_COST_BASES = frozenset(
    {"unknown", "official_provider_usage", "official_fixed_video", "official_per_second"}
)
_VIDEO_CONTENT_TYPE = "video/mp4"
_VIDEO_SUFFIX = ".mp4"
_PENDING_PROVIDER_STATES = frozenset({"queued", "in_progress", "processing"})


class VideoExecutionError(RuntimeError):
    """Durable video execution contract cannot proceed safely."""


class VideoSceneLeaseLost(VideoExecutionError):
    """A stale worker attempted to act on a reclaimed video scene."""


@dataclass(frozen=True, slots=True)
class VideoSceneClaim:
    scene_execution_id: str
    video_execution_id: str
    lease_token: str
    fencing_token: int
    mode: str
    provider_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class VideoExecutionSpec:
    organization_id: str
    requested_by_id: str
    plan: VideoPlan
    idempotency_key: str
    workspace_id: str | None = None
    project_id: str | None = None
    studio_job_id: str | None = None
    studio_asset_id: str | None = None
    estimated_cost_usd: float = 0.0
    max_attempts: int = 3
    max_polls: int = 360


def _now() -> datetime:
    return datetime.now(UTC)


def _stable_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _metadata_key_is_sensitive(key: str) -> bool:
    lowered = key.lower()
    fragments = (
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "secret",
        "prompt",
        "signed_url",
        "presigned",
        "video_data",
        "base64",
    )
    return (
        any(fragment in lowered for fragment in fragments)
        or lowered == "token"
        or lowered.endswith("_token")
        or lowered.startswith("token_")
    )


def _safe_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, raw_value in list(payload.items())[:64]:
        key = str(raw_key)[:120]
        if _metadata_key_is_sensitive(key):
            continue
        if raw_value is None or isinstance(raw_value, (bool, int, float)):
            result[key] = raw_value
        elif isinstance(raw_value, str):
            result[key] = raw_value[:500]
        elif isinstance(raw_value, dict):
            result[key] = _safe_metadata(raw_value)
        elif isinstance(raw_value, list):
            safe_items: list[Any] = []
            for item in raw_value[:32]:
                if item is None or isinstance(item, (bool, int, float)):
                    safe_items.append(item)
                elif isinstance(item, str):
                    safe_items.append(item[:500])
                elif isinstance(item, dict):
                    safe_items.append(_safe_metadata(item))
            result[key] = safe_items
    return result


def _selected_provider(plan: VideoPlan) -> tuple[str, str]:
    if not plan.compiled_scenes:
        raise VideoExecutionError("video plan has no compiled scenes")
    provider = plan.compiled_scenes[0].provider
    model = plan.compiled_scenes[0].model
    if any(item.provider != provider or item.model != model for item in plan.compiled_scenes):
        raise VideoExecutionError("video plan scenes must use one governed provider/model route")
    return provider, model


def _capability(plan: VideoPlan):
    provider, model = _selected_provider(plan)
    for item in VIDEO_PROVIDER_CAPABILITIES:
        if (
            item.provider == provider
            and item.model == model
            and plan.request.operation in item.operations
        ):
            return item
    raise VideoExecutionError("provider/model/operation is outside the governed video launch matrix")


def _validate_spec(spec: VideoExecutionSpec) -> None:
    plan = spec.plan
    capability = _capability(plan)
    if plan.render_status != "planned":
        raise VideoExecutionError("video execution requires a planned video contract")
    if not 1 <= len(plan.scenes) <= 100:
        raise VideoExecutionError("video execution scene count is outside the allowed range")
    if len(plan.compiled_scenes) != len(plan.scenes):
        raise VideoExecutionError("video plan compiled-scene count is inconsistent")
    if [item.scene_id for item in plan.compiled_scenes] != [item.scene_id for item in plan.scenes]:
        raise VideoExecutionError("video plan compiled-scene identity is inconsistent")
    if plan.request.aspect_ratio not in capability.aspect_ratios:
        raise VideoExecutionError("video aspect ratio is unsupported by provider model")
    if plan.request.resolution not in capability.resolutions:
        raise VideoExecutionError("video resolution is unsupported by provider model")
    if not 1 <= spec.max_attempts <= 5:
        raise VideoExecutionError("video scene retry limit is outside the allowed range")
    if not 1 <= spec.max_polls <= 10_000:
        raise VideoExecutionError("video scene poll limit is outside the allowed range")
    if not 8 <= len(spec.idempotency_key.strip()) <= 160:
        raise VideoExecutionError("video execution idempotency key is invalid")
    if spec.estimated_cost_usd < 0 or spec.estimated_cost_usd > 500:
        raise VideoExecutionError("video estimated cost is outside the allowed range")


def _safe_plan_metadata(plan: VideoPlan) -> dict[str, Any]:
    provider, model = _selected_provider(plan)
    compiled = {item.scene_id: item for item in plan.compiled_scenes}
    return {
        "schema": "36F.video-execution.v1",
        "plan_sha256": plan.checksum,
        "continuity_id": plan.continuity_id,
        "provider": provider,
        "model": model,
        "operation": plan.request.operation,
        "use_case": plan.request.use_case,
        "aspect_ratio": plan.request.aspect_ratio,
        "resolution": plan.request.resolution,
        "scene_count": len(plan.scenes),
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "duration_seconds": scene.duration_seconds,
                "prompt_sha256": hashlib.sha256(
                    compiled[scene.scene_id].prompt.encode("utf-8")
                ).hexdigest(),
            }
            for scene in plan.scenes
        ],
    }


def _graph_spec(plan: VideoPlan) -> MediaGraphSpec:
    provider, model = _selected_provider(plan)
    compiled = {item.scene_id: item for item in plan.compiled_scenes}
    nodes: list[MediaNodeSpec] = []
    edges: list[MediaEdgeSpec] = []
    for index, scene in enumerate(plan.scenes):
        item = compiled[scene.scene_id]
        prompt_sha = hashlib.sha256(item.prompt.encode("utf-8")).hexdigest()
        key = f"provider-scene-{index + 1:03d}-{scene.scene_id}"
        nodes.append(
            MediaNodeSpec(
                key=key,
                node_type="provider-video",
                media_type=_VIDEO_CONTENT_TYPE,
                parameters={
                    "executor": "video-provider",
                    "provider_operation": plan.request.operation,
                    "provider": provider,
                    "model": model,
                    "duration_seconds": scene.duration_seconds,
                    "aspect_ratio": plan.request.aspect_ratio,
                    "resolution": plan.request.resolution,
                },
                prompt_metadata={
                    "video_provider": {
                        "compiled_prompt": item.prompt,
                        "prompt_sha256": prompt_sha,
                        "endpoint_kind": item.endpoint_kind,
                    }
                },
                provenance=(
                    {
                        "type": "phase36f-video-plan-scene",
                        "plan_sha256": plan.checksum,
                        "continuity_id": plan.continuity_id,
                        "scene_id": scene.scene_id,
                    },
                ),
                scene_metadata={
                    "id": scene.scene_id,
                    "purpose": scene.purpose,
                    "index": index + 1,
                    "continuity_id": plan.continuity_id,
                },
                timeline_metadata={
                    "duration_seconds": scene.duration_seconds,
                    "ordinal": index,
                    "transition": scene.transition,
                },
            )
        )
        edges.append(MediaEdgeSpec(parent=key, child="assembly", ordinal=index))
    nodes.append(
        MediaNodeSpec(
            key="assembly",
            node_type="assembly",
            media_type=_VIDEO_CONTENT_TYPE,
            parameters={
                "operation": "assemble",
                "output_profile": "video-mp4-h264",
                "hardware_adapter": "software",
                "engine": "ffmpeg",
            },
            provenance=(
                {
                    "type": "phase36f-video-plan-assembly",
                    "plan_sha256": plan.checksum,
                    "continuity_id": plan.continuity_id,
                },
            ),
            timeline_metadata={"scene_count": len(plan.scenes)},
        )
    )
    return MediaGraphSpec(
        title=plan.request.title,
        asset_kind="video",
        nodes=tuple(nodes),
        edges=tuple(edges),
        output_profile="video-mp4-h264",
        rights_metadata={},
        provenance=(
            {
                "type": "phase36f-video-plan",
                "plan_sha256": plan.checksum,
                "continuity_id": plan.continuity_id,
            },
        ),
    )


async def create_video_execution(
    session: AsyncSession, *, spec: VideoExecutionSpec
) -> VideoExecution:
    """Persist a planned multi-scene execution. It cannot spend until explicitly armed."""
    _validate_spec(spec)
    key = spec.idempotency_key.strip()
    existing = await session.scalar(
        select(VideoExecution).where(
            VideoExecution.organization_id == spec.organization_id,
            VideoExecution.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing

    plan = spec.plan
    provider, model = _selected_provider(plan)
    graph = await create_media_graph(
        session,
        scope=MediaGraphScope(
            organization_id=spec.organization_id,
            created_by_id=spec.requested_by_id,
            workspace_id=spec.workspace_id,
            project_id=spec.project_id,
            studio_job_id=spec.studio_job_id,
            studio_asset_id=spec.studio_asset_id,
        ),
        spec=_graph_spec(plan),
        idempotency_key=_stable_key(spec.organization_id, key, "video-graph"),
    )
    node_rows = list(
        (
            await session.scalars(
                select(MediaAssetNode)
                .where(MediaAssetNode.graph_id == graph.id)
                .order_by(MediaAssetNode.logical_key)
            )
        ).all()
    )
    node_by_key = {item.logical_key: item for item in node_rows}
    parent = VideoExecution(
        id=uuid_str(),
        organization_id=spec.organization_id,
        workspace_id=spec.workspace_id,
        project_id=spec.project_id,
        studio_job_id=spec.studio_job_id,
        studio_asset_id=spec.studio_asset_id,
        graph_id=graph.id,
        requested_by_id=spec.requested_by_id,
        provider=provider,
        model=model,
        operation=plan.request.operation,
        status="planned",
        idempotency_key=key,
        plan_sha256=plan.checksum,
        continuity_id=plan.continuity_id,
        plan_metadata=_safe_plan_metadata(plan),
        request_options={
            "aspect_ratio": plan.request.aspect_ratio,
            "resolution": plan.request.resolution,
            "reference_count": plan.request.reference_count,
        },
        scene_count=len(plan.scenes),
        resume_count=0,
        estimated_cost_usd=float(spec.estimated_cost_usd),
        actual_cost_usd=None,
        cost_basis="unknown",
    )
    session.add(parent)
    await session.flush()

    scene_estimate = float(spec.estimated_cost_usd) / len(plan.scenes) if plan.scenes else 0.0
    compiled = {item.scene_id: item for item in plan.compiled_scenes}
    for index, scene in enumerate(plan.scenes):
        item = compiled[scene.scene_id]
        node_key = f"provider-scene-{index + 1:03d}-{scene.scene_id}"
        target = node_by_key.get(node_key)
        if target is None or target.status != "planned" or target.storage_key or target.checksum:
            raise VideoExecutionError("video scene graph target is unavailable or not fresh")
        prompt_sha = hashlib.sha256(item.prompt.encode("utf-8")).hexdigest()
        session.add(
            VideoSceneExecution(
                id=uuid_str(),
                video_execution_id=parent.id,
                organization_id=spec.organization_id,
                graph_id=graph.id,
                target_node_id=target.id,
                scene_key=scene.scene_id,
                scene_index=index,
                provider=provider,
                model=model,
                operation=plan.request.operation,
                status="planned",
                idempotency_key=_stable_key(spec.organization_id, key, scene.scene_id),
                prompt_sha256=prompt_sha,
                request_options={
                    **dict(item.settings),
                    "continuity_id": plan.continuity_id,
                    "scene_id": scene.scene_id,
                },
                attempts=0,
                max_attempts=spec.max_attempts,
                poll_count=0,
                max_polls=spec.max_polls,
                fencing_token=0,
                provider_state="not_started",
                provider_progress=None,
                provider_response_metadata={},
                usage_metadata={},
                estimated_cost_usd=scene_estimate,
                actual_cost_usd=None,
                cost_basis="unknown",
            )
        )
    graph.graph_metadata = {
        **(graph.graph_metadata or {}),
        "video_execution": {
            "execution_id": parent.id,
            "schema": "36F.video-execution.v1",
            "plan_sha256": plan.checksum,
            "continuity_id": plan.continuity_id,
        },
    }
    await session.flush()
    return parent


async def arm_video_execution(
    session: AsyncSession, *, execution_id: str, organization_id: str
) -> VideoExecution:
    parent = await session.scalar(
        select(VideoExecution)
        .where(
            VideoExecution.id == execution_id,
            VideoExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if parent is None:
        raise VideoExecutionError("video execution not found")
    if parent.status in {"queued", "running"}:
        return parent
    if parent.status != "planned":
        raise VideoExecutionError("only planned video executions may be armed")
    scenes = list(
        (
            await session.scalars(
                select(VideoSceneExecution)
                .where(VideoSceneExecution.video_execution_id == parent.id)
                .order_by(VideoSceneExecution.scene_index)
                .with_for_update()
            )
        ).all()
    )
    if len(scenes) != int(parent.scene_count) or any(item.status != "planned" for item in scenes):
        raise VideoExecutionError("video execution scenes are not fresh planned rows")
    parent.status = "queued"
    parent.armed_at = _now()
    parent.error_code = None
    parent.error_message = None
    for scene in scenes:
        scene.status = "queued"
        scene.available_at = None
        scene.error_code = None
        scene.error_message = None
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=None,
            action="video.execution.armed",
            resource_type="video_execution",
            resource_id=parent.id,
            details={
                "graph_id": parent.graph_id,
                "provider": parent.provider,
                "model": parent.model,
                "operation": parent.operation,
                "scene_count": parent.scene_count,
                "plan_sha256": parent.plan_sha256,
            },
        )
    )
    await session.flush()
    return parent


async def resume_failed_video_execution(
    session: AsyncSession, *, execution_id: str, organization_id: str
) -> VideoExecution:
    parent = await session.scalar(
        select(VideoExecution)
        .where(
            VideoExecution.id == execution_id,
            VideoExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if parent is None:
        raise VideoExecutionError("video execution not found")
    if parent.status != "failed":
        raise VideoExecutionError("only failed video executions may be resumed")
    scenes = list(
        (
            await session.scalars(
                select(VideoSceneExecution)
                .where(VideoSceneExecution.video_execution_id == parent.id)
                .order_by(VideoSceneExecution.scene_index)
                .with_for_update()
            )
        ).all()
    )
    failed = [item for item in scenes if item.status == "failed"]
    if not failed:
        raise VideoExecutionError("failed video execution has no failed scenes to resume")
    for scene in failed:
        scene.status = "queued"
        scene.attempts = 0
        scene.lease_token = None
        scene.lease_owner = None
        scene.lease_expires_at = None
        scene.available_at = None
        scene.provider_request_id = None
        scene.provider_state = "not_started"
        scene.provider_progress = None
        scene.poll_count = 0
        scene.provider_submitted_at = None
        scene.last_polled_at = None
        scene.provider_response_metadata = {}
        scene.usage_metadata = {}
        scene.actual_cost_usd = None
        scene.cost_basis = "unknown"
        scene.error_code = None
        scene.error_message = None
        scene.completed_at = None
    parent.status = "queued"
    parent.resume_count = int(parent.resume_count) + 1
    parent.error_code = None
    parent.error_message = None
    parent.completed_at = None
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=None,
            action="video.execution.resumed",
            resource_type="video_execution",
            resource_id=parent.id,
            details={
                "graph_id": parent.graph_id,
                "resumed_scene_ids": [item.id for item in failed],
                "resume_count": parent.resume_count,
            },
        )
    )
    await session.flush()
    return parent


class VideoSceneExecutionAuthority:
    def __init__(
        self,
        *,
        session_factory: SessionFactory = SessionLocal,
        store: MediaObjectStore | None = None,
        worker_id: str = "video-provider-worker",
        lease_seconds: int = 600,
    ) -> None:
        if not 30 <= lease_seconds <= 3600:
            raise ValueError("video scene lease duration is outside the allowed range")
        self.session_factory = session_factory
        self.store = store or media_object_store()
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    async def reap_exhausted(self) -> int:
        """Dead-letter scenes whose bounded submit/reconcile/poll budget is exhausted."""
        now = _now()
        async with self.session_factory() as session:
            submission_exhausted = and_(
                VideoSceneExecution.provider_request_id.is_(None),
                VideoSceneExecution.provider_state != "submitting",
                VideoSceneExecution.attempts >= VideoSceneExecution.max_attempts,
            )
            polling_exhausted = and_(
                or_(
                    VideoSceneExecution.provider_request_id.is_not(None),
                    VideoSceneExecution.provider_state == "submitting",
                ),
                VideoSceneExecution.poll_count >= VideoSceneExecution.max_polls,
            )
            rows = list(
                (
                    await session.scalars(
                        select(VideoSceneExecution)
                        .where(
                            VideoSceneExecution.status.in_(("queued", "running")),
                            or_(submission_exhausted, polling_exhausted),
                            or_(
                                VideoSceneExecution.status == "queued",
                                VideoSceneExecution.lease_expires_at.is_(None),
                                VideoSceneExecution.lease_expires_at <= now,
                            ),
                        )
                        .with_for_update(skip_locked=True)
                    )
                ).all()
            )
            parent_ids = {row.video_execution_id for row in rows}
            parents: dict[str, VideoExecution] = {}
            for parent_id in parent_ids:
                parent = await session.scalar(
                    select(VideoExecution)
                    .where(VideoExecution.id == parent_id)
                    .with_for_update()
                )
                if parent is not None:
                    parents[parent_id] = parent
            for row in rows:
                code = (
                    "video_scene_poll_exhausted"
                    if row.provider_request_id or row.provider_state == "submitting"
                    else "video_scene_submission_exhausted"
                )
                row.status = "failed"
                row.error_code = code
                row.error_message = "Video scene exhausted its bounded submit/reconcile/poll budget"
                row.lease_token = None
                row.lease_owner = None
                row.lease_expires_at = None
                row.available_at = None
                row.completed_at = now
                if row.provider_request_id:
                    row.provider_state = "failed"
                parent = parents.get(row.video_execution_id)
                if parent is not None:
                    parent.status = "failed"
                    parent.error_code = code
                    parent.error_message = row.error_message
                    parent.completed_at = now
                session.add(
                    AuditEvent(
                        organization_id=row.organization_id,
                        user_id=None,
                        action="video.scene.dead_lettered",
                        resource_type="video_scene_execution",
                        resource_id=row.id,
                        details={
                            "video_execution_id": row.video_execution_id,
                            "scene_key": row.scene_key,
                            "provider": row.provider,
                            "model": row.model,
                            "provider_job_recorded": bool(row.provider_request_id),
                            "attempts": row.attempts,
                            "poll_count": row.poll_count,
                        },
                    )
                )
            if rows:
                await session.commit()
            return len(rows)

    async def claim(self) -> VideoSceneClaim | None:
        await self.reap_exhausted()
        now = _now()
        prior = aliased(VideoSceneExecution)
        parent_alias = aliased(VideoExecution)
        blocked_prior = (
            select(prior.id)
            .where(
                prior.video_execution_id == VideoSceneExecution.video_execution_id,
                prior.scene_index < VideoSceneExecution.scene_index,
                prior.status != "completed",
            )
            .exists()
        )
        submission_budget = and_(
            VideoSceneExecution.provider_request_id.is_(None),
            VideoSceneExecution.provider_state != "submitting",
            VideoSceneExecution.attempts < VideoSceneExecution.max_attempts,
        )
        reconciliation_budget = and_(
            VideoSceneExecution.provider_request_id.is_(None),
            VideoSceneExecution.provider_state == "submitting",
            VideoSceneExecution.poll_count < VideoSceneExecution.max_polls,
        )
        poll_budget = and_(
            VideoSceneExecution.provider_request_id.is_not(None),
            VideoSceneExecution.poll_count < VideoSceneExecution.max_polls,
        )
        ready = and_(
            VideoSceneExecution.status == "queued",
            or_(
                VideoSceneExecution.available_at.is_(None),
                VideoSceneExecution.available_at <= now,
            ),
        )
        recovery = and_(
            VideoSceneExecution.status == "running",
            VideoSceneExecution.lease_expires_at.is_not(None),
            VideoSceneExecution.lease_expires_at <= now,
        )
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoSceneExecution)
                .join(parent_alias, parent_alias.id == VideoSceneExecution.video_execution_id)
                .where(
                    parent_alias.status.in_(("queued", "running")),
                    or_(ready, recovery),
                    or_(submission_budget, reconciliation_budget, poll_budget),
                    ~blocked_prior,
                )
                .order_by(VideoSceneExecution.created_at, VideoSceneExecution.scene_index)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            parent = await session.scalar(
                select(VideoExecution)
                .where(VideoExecution.id == row.video_execution_id)
                .with_for_update()
            )
            if parent is None or parent.status not in {"queued", "running"}:
                return None
            if row.provider_request_id:
                mode = "poll"
                row.poll_count = int(row.poll_count) + 1
                row.last_polled_at = now
            elif row.provider_state == "submitting":
                mode = "reconcile"
                row.poll_count = int(row.poll_count) + 1
                row.last_polled_at = now
            else:
                mode = "submit"
                row.attempts = int(row.attempts) + 1
            row.status = "running"
            row.fencing_token = int(row.fencing_token) + 1
            row.lease_token = str(uuid4())
            row.lease_owner = self.worker_id
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            row.available_at = None
            row.started_at = row.started_at or now
            row.error_code = None
            row.error_message = None
            parent.status = "running"
            parent.started_at = parent.started_at or now
            await session.commit()
            return VideoSceneClaim(
                scene_execution_id=row.id,
                video_execution_id=row.video_execution_id,
                lease_token=str(row.lease_token),
                fencing_token=int(row.fencing_token),
                mode=mode,
                provider_request_id=row.provider_request_id,
            )

    def _owns(self, row: VideoSceneExecution | None, claim: VideoSceneClaim) -> bool:
        return bool(
            row is not None
            and row.status == "running"
            and row.lease_owner == self.worker_id
            and row.lease_token == claim.lease_token
            and int(row.fencing_token) == claim.fencing_token
        )

    def _require_owned(
        self, row: VideoSceneExecution | None, claim: VideoSceneClaim
    ) -> VideoSceneExecution:
        if not self._owns(row, claim):
            raise VideoSceneLeaseLost(claim.scene_execution_id)
        assert row is not None
        return row

    async def renew(self, claim: VideoSceneClaim) -> None:
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoSceneExecution)
                .where(VideoSceneExecution.id == claim.scene_execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            row.lease_expires_at = _now() + timedelta(seconds=self.lease_seconds)
            await session.commit()

    async def mark_submission_started(self, claim: VideoSceneClaim) -> None:
        """Durably mark the ambiguous submit window before provider HTTP is attempted."""
        if claim.mode != "submit":
            raise VideoExecutionError("only a submit claim may start video provider submission")
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoSceneExecution)
                .where(VideoSceneExecution.id == claim.scene_execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_request_id:
                raise VideoExecutionError("video scene provider job is already recorded")
            if row.provider_state != "not_started":
                raise VideoExecutionError("video scene provider submission state is not fresh")
            row.provider_state = "submitting"
            row.provider_submitted_at = row.provider_submitted_at or _now()
            await session.commit()

    def _requeue(self, row: VideoSceneExecution, *, poll_after_seconds: int) -> None:
        delay = max(1, min(int(poll_after_seconds), 300))
        row.status = "queued"
        row.available_at = _now() + timedelta(seconds=delay)
        row.lease_token = None
        row.lease_owner = None
        row.lease_expires_at = None

    async def record_provider_request(
        self,
        claim: VideoSceneClaim,
        *,
        provider_request_id: str,
        provider_state: str = "queued",
        provider_response_metadata: dict[str, Any] | None = None,
        progress: int | None = None,
        poll_after_seconds: int = 5,
    ) -> None:
        if claim.mode not in {"submit", "reconcile"}:
            raise VideoExecutionError(
                "provider job identity may be recorded only by submit/reconcile claims"
            )
        request_id = provider_request_id.strip()
        if not 1 <= len(request_id) <= 240:
            raise VideoExecutionError("video provider request id is invalid")
        if provider_state not in _PENDING_PROVIDER_STATES:
            raise VideoExecutionError("video provider job state is not pending")
        if progress is not None and not 0 <= progress <= 99:
            raise VideoExecutionError("video provider progress is outside the pending range")
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoSceneExecution)
                .where(VideoSceneExecution.id == claim.scene_execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if row.provider_request_id and row.provider_request_id != request_id:
                raise VideoExecutionError("video scene provider job identity cannot change")
            if not row.provider_request_id and row.provider_state != "submitting":
                raise VideoExecutionError(
                    "video provider submission was not durably marked before HTTP"
                )
            row.provider_request_id = request_id
            row.provider_state = provider_state
            row.provider_progress = progress
            row.provider_submitted_at = row.provider_submitted_at or _now()
            row.provider_response_metadata = _safe_metadata(provider_response_metadata or {})
            self._requeue(row, poll_after_seconds=poll_after_seconds)
            await session.commit()

    async def record_poll_pending(
        self,
        claim: VideoSceneClaim,
        *,
        provider_state: str,
        provider_response_metadata: dict[str, Any],
        progress: int | None = None,
        poll_after_seconds: int = 5,
    ) -> None:
        if claim.mode != "poll":
            raise VideoExecutionError("provider pending state may be recorded only by a poll claim")
        if provider_state not in _PENDING_PROVIDER_STATES:
            raise VideoExecutionError("video provider poll state is not pending")
        if progress is not None and not 0 <= progress <= 99:
            raise VideoExecutionError("video provider progress is outside the pending range")
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoSceneExecution)
                .where(VideoSceneExecution.id == claim.scene_execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            if not row.provider_request_id:
                raise VideoExecutionError("video provider job must be recorded before polling")
            row.provider_state = provider_state
            row.provider_progress = progress
            row.last_polled_at = _now()
            row.provider_response_metadata = {
                **(row.provider_response_metadata or {}),
                **_safe_metadata(provider_response_metadata),
            }
            self._requeue(row, poll_after_seconds=poll_after_seconds)
            await session.commit()

    async def fail(
        self,
        claim: VideoSceneClaim,
        *,
        code: str,
        message: str,
        permanent: bool = False,
        retry_after_seconds: int = 5,
        submission_safe_to_retry: bool = False,
    ) -> None:
        safe_code = code.strip()[:120] or "video_scene_failure"
        safe_message = message.strip()[:1000] or "Video scene execution failed"
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoSceneExecution)
                .where(VideoSceneExecution.id == claim.scene_execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            parent = await session.scalar(
                select(VideoExecution)
                .where(VideoExecution.id == row.video_execution_id)
                .with_for_update()
            )
            if parent is None:
                raise VideoExecutionError("video execution disappeared")
            if submission_safe_to_retry:
                if claim.mode != "submit":
                    raise VideoExecutionError(
                        "only a submit claim may reopen a definitive scene submission retry"
                    )
                if row.provider_request_id or row.provider_state != "submitting":
                    raise VideoExecutionError(
                        "submission retry may be reopened only after a definitively rejected fresh submission"
                    )
                row.provider_state = "not_started"
            exhausted = permanent or (
                (
                    not row.provider_request_id
                    and row.provider_state != "submitting"
                    and row.attempts >= row.max_attempts
                )
                or (
                    (bool(row.provider_request_id) or row.provider_state == "submitting")
                    and row.poll_count >= row.max_polls
                )
            )
            row.error_code = safe_code
            row.error_message = safe_message
            if exhausted:
                row.status = "failed"
                if row.provider_request_id:
                    row.provider_state = "failed"
                row.completed_at = _now()
                row.available_at = None
                parent.status = "failed"
                parent.error_code = safe_code
                parent.error_message = safe_message
                parent.completed_at = _now()
            else:
                row.status = "queued"
                row.available_at = _now() + timedelta(
                    seconds=max(1, min(int(retry_after_seconds), 300))
                )
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            await session.commit()

    @staticmethod
    def _inspect_mp4(body: bytes) -> None:
        if len(body) < 24 or body[4:8] != b"ftyp":
            raise VideoExecutionError("video provider output is not a recognizable MP4 container")

    async def complete_scene_bytes(
        self,
        claim: VideoSceneClaim,
        *,
        body: bytes,
        content_type: str,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str = "unknown",
    ) -> dict[str, Any]:
        if claim.mode != "poll":
            raise VideoExecutionError("video scene completion requires a poll claim")
        if content_type != _VIDEO_CONTENT_TYPE:
            raise VideoExecutionError("video scene content type must be video/mp4")
        self._inspect_mp4(body)
        if actual_cost_usd is not None and (actual_cost_usd < 0 or actual_cost_usd > 250):
            raise VideoExecutionError("video scene actual cost is outside the allowed range")
        safe_cost_basis = cost_basis.strip()[:64] or "unknown"
        if safe_cost_basis not in _ALLOWED_COST_BASES:
            raise VideoExecutionError("video scene cost basis is unsupported")
        async with self.session_factory() as session:
            row = await session.get(VideoSceneExecution, claim.scene_execution_id)
            row = self._require_owned(row, claim)
            if not row.provider_request_id:
                raise VideoExecutionError("video provider job is missing at scene completion")
            key = (
                f"media/{row.organization_id}/video/{row.graph_id}/{row.target_node_id}/"
                f"f{claim.fencing_token}{_VIDEO_SUFFIX}"
            )
        stored = await asyncio.to_thread(
            self.store.put_bytes,
            key,
            body,
            content_type,
            metadata={
                "video-execution-id": claim.video_execution_id,
                "scene-execution-id": claim.scene_execution_id,
                "fencing-token": str(claim.fencing_token),
            },
        )
        try:
            return await self._complete_stored(
                claim,
                storage_backend=stored.backend,
                storage_key=stored.key,
                checksum=stored.sha256,
                size_bytes=stored.size_bytes,
                content_type=content_type,
                provider_response_metadata=_safe_metadata(provider_response_metadata),
                usage_metadata=_safe_metadata(usage_metadata),
                actual_cost_usd=actual_cost_usd,
                cost_basis=safe_cost_basis,
            )
        except Exception:
            await asyncio.to_thread(self.store.delete, stored.key)
            raise

    async def _complete_stored(
        self,
        claim: VideoSceneClaim,
        *,
        storage_backend: str,
        storage_key: str,
        checksum: str,
        size_bytes: int,
        content_type: str,
        provider_response_metadata: dict[str, Any],
        usage_metadata: dict[str, Any],
        actual_cost_usd: float | None,
        cost_basis: str,
    ) -> dict[str, Any]:
        completed = _now()
        async with self.session_factory() as session:
            row = await session.scalar(
                select(VideoSceneExecution)
                .where(VideoSceneExecution.id == claim.scene_execution_id)
                .with_for_update()
            )
            row = self._require_owned(row, claim)
            parent = await session.scalar(
                select(VideoExecution)
                .where(VideoExecution.id == row.video_execution_id)
                .with_for_update()
            )
            target = await session.scalar(
                select(MediaAssetNode)
                .where(
                    MediaAssetNode.id == row.target_node_id,
                    MediaAssetNode.graph_id == row.graph_id,
                    MediaAssetNode.organization_id == row.organization_id,
                )
                .with_for_update()
            )
            if parent is None or target is None:
                raise VideoExecutionError("video execution graph target disappeared")
            if target.status != "planned" or target.storage_key or target.checksum:
                raise VideoExecutionError("video scene target is no longer a fresh planned node")
            target.status = "completed"
            target.storage_backend = storage_backend
            target.storage_key = storage_key
            target.checksum = checksum
            target.size_bytes = size_bytes
            target.media_type = content_type
            target.provenance = [
                *(target.provenance or []),
                {
                    "type": "provider-video",
                    "provider": row.provider,
                    "model": row.model,
                    "operation": row.operation,
                    "provider_request_id": row.provider_request_id,
                    "prompt_sha256": row.prompt_sha256,
                    "output_checksum": checksum,
                    "fencing_token": claim.fencing_token,
                    "completed_at": completed.isoformat(),
                },
            ]
            row.status = "completed"
            row.provider_state = "completed"
            row.provider_progress = 100
            row.provider_response_metadata = dict(provider_response_metadata)
            row.usage_metadata = dict(usage_metadata)
            row.actual_cost_usd = float(actual_cost_usd) if actual_cost_usd is not None else None
            row.cost_basis = cost_basis
            row.output_storage_backend = storage_backend
            row.output_storage_key = storage_key
            row.output_checksum = checksum
            row.output_size_bytes = size_bytes
            row.output_media_type = content_type
            row.completed_at = completed
            row.last_polled_at = completed
            row.lease_token = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = None
            row.error_code = None
            row.error_message = None

            remaining = int(
                await session.scalar(
                    select(func.count(VideoSceneExecution.id)).where(
                        VideoSceneExecution.video_execution_id == parent.id,
                        VideoSceneExecution.status != "completed",
                    )
                )
                or 0
            )
            completed_count = int(parent.scene_count) - remaining
            actual_count = int(
                await session.scalar(
                    select(func.count(VideoSceneExecution.id)).where(
                        VideoSceneExecution.video_execution_id == parent.id,
                        VideoSceneExecution.status == "completed",
                        VideoSceneExecution.actual_cost_usd.is_not(None),
                    )
                )
                or 0
            )
            if remaining == 0:
                parent.status = "scenes_completed"
                if actual_count == completed_count:
                    parent.actual_cost_usd = float(
                        await session.scalar(
                            select(func.coalesce(func.sum(VideoSceneExecution.actual_cost_usd), 0.0)).where(
                                VideoSceneExecution.video_execution_id == parent.id
                            )
                        )
                        or 0.0
                    )
                    bases = set(
                        (
                            await session.scalars(
                                select(VideoSceneExecution.cost_basis).where(
                                    VideoSceneExecution.video_execution_id == parent.id
                                )
                            )
                        ).all()
                    )
                    parent.cost_basis = bases.pop() if len(bases) == 1 else "unknown"
                else:
                    parent.actual_cost_usd = None
                    parent.cost_basis = "unknown"
            else:
                parent.status = "running"
            parent.error_code = None
            parent.error_message = None
            session.add(
                AuditEvent(
                    organization_id=row.organization_id,
                    user_id=None,
                    action="video.scene.completed",
                    resource_type="video_scene_execution",
                    resource_id=row.id,
                    details={
                        "video_execution_id": parent.id,
                        "graph_id": row.graph_id,
                        "scene_key": row.scene_key,
                        "scene_index": row.scene_index,
                        "provider": row.provider,
                        "model": row.model,
                        "output_checksum": checksum,
                        "fencing_token": claim.fencing_token,
                    },
                )
            )
            await session.commit()
            return {
                "video_execution_id": parent.id,
                "scene_execution_id": row.id,
                "scene_key": row.scene_key,
                "scene_status": row.status,
                "video_status": parent.status,
                "output_checksum": checksum,
                "storage_backend": storage_backend,
            }


async def finalize_assembled_execution(
    session: AsyncSession, *, execution_id: str, organization_id: str
) -> VideoExecution:
    parent = await session.scalar(
        select(VideoExecution)
        .where(
            VideoExecution.id == execution_id,
            VideoExecution.organization_id == organization_id,
        )
        .with_for_update()
    )
    if parent is None:
        raise VideoExecutionError("video execution not found")
    if parent.status == "completed":
        return parent
    if parent.status != "scenes_completed":
        raise VideoExecutionError("video execution scenes are not complete")
    graph = await session.scalar(
        select(MediaAssetGraph)
        .where(
            MediaAssetGraph.id == parent.graph_id,
            MediaAssetGraph.organization_id == organization_id,
        )
        .with_for_update()
    )
    assembly = await session.scalar(
        select(MediaAssetNode)
        .where(
            MediaAssetNode.graph_id == parent.graph_id,
            MediaAssetNode.organization_id == organization_id,
            MediaAssetNode.logical_key == "assembly",
        )
        .with_for_update()
    )
    if graph is None or assembly is None:
        raise VideoExecutionError("video assembly graph is unavailable")
    if (
        graph.status != "completed"
        or assembly.status != "completed"
        or not assembly.storage_key
        or not assembly.checksum
        or not assembly.size_bytes
    ):
        raise VideoExecutionError("video assembly is not complete")
    parent.status = "completed"
    parent.final_storage_backend = assembly.storage_backend
    parent.final_storage_key = assembly.storage_key
    parent.final_checksum = assembly.checksum
    parent.final_size_bytes = assembly.size_bytes
    parent.final_media_type = assembly.media_type or _VIDEO_CONTENT_TYPE
    parent.completed_at = _now()
    parent.error_code = None
    parent.error_message = None
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=None,
            action="video.execution.completed",
            resource_type="video_execution",
            resource_id=parent.id,
            details={
                "graph_id": parent.graph_id,
                "final_checksum": parent.final_checksum,
                "scene_count": parent.scene_count,
                "resume_count": parent.resume_count,
            },
        )
    )
    await session.flush()
    return parent
