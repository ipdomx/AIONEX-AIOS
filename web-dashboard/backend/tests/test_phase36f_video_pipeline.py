from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from aios.video_factory import VideoRequest, VideoRuntimeEvidence
from app.db.base import SessionLocal
from app.db.models import (
    MediaAssetNode,
    MediaRenderStep,
    Organization,
    Project,
    StudioAsset,
    StudioJob,
    User,
    VideoExecution,
    Workspace,
)
from app.services.media_graph_runtime import MediaGraphScope
from app.services.video_pipeline import VideoPipelineError, create_routed_video_pipeline


class Scope:
    def __init__(self, org, user, workspace, project, job, asset) -> None:
        self.org = org
        self.user = user
        self.workspace = workspace
        self.project = project
        self.job = job
        self.asset = asset

    def media_scope(self) -> MediaGraphScope:
        return MediaGraphScope(
            organization_id=self.org.id,
            created_by_id=self.user.id,
            workspace_id=self.workspace.id,
            project_id=self.project.id,
            studio_job_id=self.job.id,
            studio_asset_id=self.asset.id,
        )


async def seed_scope(tag: str) -> Scope:
    suffix = uuid4().hex[:10]
    async with SessionLocal() as session:
        org = Organization(
            name=f"P36F {tag}",
            slug=f"p36f-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(org)
        await session.flush()
        user = User(
            organization_id=org.id,
            role_id=None,
            email=f"p36f-pipeline-{suffix}@example.com",
            name="P36F",
            password_hash="unused",
            status="active",
        )
        ws = Workspace(
            organization_id=org.id,
            name="P36F",
            slug=f"p36f-pipeline-ws-{suffix}",
            status="active",
        )
        session.add_all([user, ws])
        await session.flush()
        project = Project(
            organization_id=org.id,
            workspace_id=ws.id,
            owner_id=user.id,
            name="P36F",
            slug=f"p36f-pipeline-project-{suffix}",
            description="Video pipeline",
            status="active",
            priority="high",
            progress=10,
        )
        session.add(project)
        await session.flush()
        job = StudioJob(
            organization_id=org.id,
            workspace_id=ws.id,
            project_id=project.id,
            requested_by_id=user.id,
            department="video",
            output_kind="video",
            title="P36F",
            brief="Video pipeline",
            language="en-US",
            style="cinematic",
            provider_mode="provider_neutral",
            status="completed",
            progress=100,
            safety_status="passed",
            request_metadata={},
            result_metadata={},
        )
        session.add(job)
        await session.flush()
        asset = StudioAsset(
            organization_id=org.id,
            job_id=job.id,
            project_id=project.id,
            created_by_id=user.id,
            department="video",
            asset_type="video",
            title="P36F",
            filename="planned.zip",
            media_type="application/zip",
            storage_path="/tmp/planned.zip",
            checksum="a" * 64,
            size_bytes=1,
            status="active",
            current_revision=1,
            asset_metadata={"render_status": "planned"},
        )
        session.add(asset)
        await session.commit()
        return Scope(org, user, ws, project, job, asset)


async def cleanup(scope: Scope) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(Organization).where(Organization.id == scope.org.id)
        )
        await session.commit()


def video_request(**overrides) -> VideoRequest:
    data = dict(
        title="AIONEX launch film",
        brief="Create a real cinematic product launch sequence with continuity and truthful claims.",
        operation="text-to-video",
        use_case="advertisement",
        aspect_ratio="16:9",
        resolution="720p",
        style="cinematic",
        brand_name="AIONEX",
    )
    data.update(overrides)
    return VideoRequest(**data)


def evidence(
    model: str = "sora-2", state: str = "ready"
) -> tuple[VideoRuntimeEvidence, ...]:
    return (
        VideoRuntimeEvidence(
            provider="openai",
            model=model,
            state=state,
            proven_operations=frozenset({"text-to-video"})
            if state == "ready"
            else frozenset(),
            reason="bounded Stage2B acceptance evidence",
        ),
    )


@pytest.mark.asyncio
async def test_routed_video_pipeline_is_planned_idempotent_and_ffmpeg_only_owns_assembly() -> (
    None
):
    scope = await seed_scope("route")
    try:
        async with SessionLocal() as session:
            first = await create_routed_video_pipeline(
                session,
                scope=scope.media_scope(),
                request=video_request(),
                runtime_evidence=evidence(),
                idempotency_key="p36f-pipeline-idempotent",
            )
            await session.commit()
        async with SessionLocal() as session:
            second = await create_routed_video_pipeline(
                session,
                scope=scope.media_scope(),
                request=video_request(),
                runtime_evidence=evidence(),
                idempotency_key="p36f-pipeline-idempotent",
            )
            await session.commit()
        assert second.graph_id == first.graph_id
        assert second.execution_ids == first.execution_ids
        assert first.provider == "openai" and first.model == "sora-2"
        assert first.estimated_cost_usd == pytest.approx(2.4)
        assert len(first.execution_ids) == len(first.scene_node_ids) == 4
        async with SessionLocal() as session:
            executions = list(
                (
                    await session.scalars(
                        select(VideoExecution)
                        .where(VideoExecution.graph_id == first.graph_id)
                        .order_by(VideoExecution.scene_key)
                    )
                ).all()
            )
            nodes = list(
                (
                    await session.scalars(
                        select(MediaAssetNode).where(
                            MediaAssetNode.graph_id == first.graph_id
                        )
                    )
                ).all()
            )
            steps = list(
                (
                    await session.scalars(
                        select(MediaRenderStep).where(
                            MediaRenderStep.graph_id == first.graph_id
                        )
                    )
                ).all()
            )
            assert len(executions) == 4
            assert all(
                row.status == "planned"
                and row.armed_at is None
                and row.provider_job_id is None
                for row in executions
            )
            assert sum(row.estimated_cost_usd for row in executions) == pytest.approx(
                2.4
            )
            provider_nodes = [
                node for node in nodes if node.node_type == "video-provider-scene"
            ]
            assert len(provider_nodes) == 4
            assert all(
                "operation" not in (node.operation_metadata or {})
                for node in provider_nodes
            )
            assert len(steps) == 1
            assert steps[0].operation == "assemble" and steps[0].status == "planned"
            assert steps[0].target_node_id == first.assembly_node_id
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_inventory_visible_evidence_cannot_create_graph_or_video_execution() -> (
    None
):
    scope = await seed_scope("inventory")
    try:
        async with SessionLocal() as session:
            before_graphs = int(
                await session.scalar(select(func.count()).select_from(MediaAssetNode))
                or 0
            )
            before_execs = int(
                await session.scalar(select(func.count()).select_from(VideoExecution))
                or 0
            )
            with pytest.raises(VideoPipelineError, match="no live-proven"):
                await create_routed_video_pipeline(
                    session,
                    scope=scope.media_scope(),
                    request=video_request(),
                    runtime_evidence=evidence(state="inventory_visible"),
                    idempotency_key="p36f-no-live",
                )
            await session.rollback()
        async with SessionLocal() as session:
            assert (
                int(
                    await session.scalar(
                        select(func.count()).select_from(MediaAssetNode)
                    )
                    or 0
                )
                == before_graphs
            )
            assert (
                int(
                    await session.scalar(
                        select(func.count()).select_from(VideoExecution)
                    )
                    or 0
                )
                == before_execs
            )
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_sora_pro_runtime_route_has_provider_specific_plan_and_cost() -> None:
    scope = await seed_scope("pro")
    try:
        async with SessionLocal() as session:
            pipeline = await create_routed_video_pipeline(
                session,
                scope=scope.media_scope(),
                request=video_request(),
                runtime_evidence=evidence(model="sora-2-pro"),
                idempotency_key="p36f-pro",
            )
            await session.commit()
        assert pipeline.model == "sora-2-pro"
        assert pipeline.estimated_cost_usd == pytest.approx(7.2)
        async with SessionLocal() as session:
            rows = list(
                (
                    await session.scalars(
                        select(VideoExecution).where(
                            VideoExecution.graph_id == pipeline.graph_id
                        )
                    )
                ).all()
            )
            assert len(rows) == 4 and all(row.model == "sora-2-pro" for row in rows)
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_reference_video_request_fails_before_graph_until_reference_pipeline_exists() -> (
    None
):
    scope = await seed_scope("reference")
    try:
        req = video_request(
            operation="logo-to-video", reference_count=1, use_case="logo-animation"
        )
        async with SessionLocal() as session:
            before = int(
                await session.scalar(select(func.count()).select_from(VideoExecution))
                or 0
            )
            with pytest.raises(VideoPipelineError, match="text-to-video only"):
                await create_routed_video_pipeline(
                    session,
                    scope=scope.media_scope(),
                    request=req,
                    runtime_evidence=(
                        VideoRuntimeEvidence(
                            provider="openai",
                            model="sora-2",
                            state="ready",
                            proven_operations=frozenset({"logo-to-video"}),
                            reason="not wired",
                        ),
                    ),
                    idempotency_key="p36f-reference",
                )
            await session.rollback()
        async with SessionLocal() as session:
            assert (
                int(
                    await session.scalar(
                        select(func.count()).select_from(VideoExecution)
                    )
                    or 0
                )
                == before
            )
    finally:
        await cleanup(scope)
