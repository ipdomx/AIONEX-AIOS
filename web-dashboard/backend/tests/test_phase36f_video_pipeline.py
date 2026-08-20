from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from aios.video_factory import VideoRequest, VideoRuntimeEvidence
from app.db.base import SessionLocal
from app.db.models import (
    AIProvider,
    MediaAssetEdge,
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
from app.core.config import settings
from app.services.ai_runtime_service import encrypt_provider_secret
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph
from app.services.media_orchestrator import MediaGraphSpec, MediaNodeSpec
from app.services.media_storage import LocalMediaObjectStore
from app.services.video_pipeline import VideoPipelineError, create_routed_video_pipeline
from app.services.video_provider_worker import VideoProviderWorker
from app.services.video_providers import ProviderVideoFailure
from app.services.video_runtime import VideoExecutionAuthority, arm_video_execution


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
    model: str = "sora-2", state: str = "ready", operation: str = "text-to-video"
) -> tuple[VideoRuntimeEvidence, ...]:
    return (
        VideoRuntimeEvidence(
            provider="openai",
            model=model,
            state=state,
            proven_operations=frozenset({operation}) if state == "ready" else frozenset(),
            reason="bounded Phase36F operation-specific acceptance evidence",
        ),
    )


async def seed_reference_node(
    scope: Scope,
    *,
    media_type: str = "image/png",
    store: LocalMediaObjectStore | None = None,
    body: bytes = b"governed-reference-image-bytes",
) -> str:
    async with SessionLocal() as session:
        graph = await create_media_graph(
            session,
            scope=scope.media_scope(),
            spec=MediaGraphSpec(
                title="P36F governed reference",
                asset_kind="image",
                nodes=(MediaNodeSpec(key="reference-source", node_type="image", media_type=media_type),),
                edges=(),
                output_profile="image-png-lossless",
            ),
            idempotency_key=f"p36f-reference-source-{uuid4()}",
        )
        node = await session.scalar(
            select(MediaAssetNode).where(
                MediaAssetNode.graph_id == graph.id,
                MediaAssetNode.logical_key == "reference-source",
            )
        )
        assert node is not None
        node.status = "completed"
        storage_key = f"reference/{node.id}.png"
        if store is not None:
            stored = store.put_bytes(storage_key, body, media_type)
            node.storage_backend = stored.backend
            node.storage_key = stored.key
            node.checksum = stored.sha256
            node.size_bytes = stored.size_bytes
        else:
            node.storage_backend = "local"
            node.storage_key = storage_key
            node.checksum = sha256(body).hexdigest()
            node.size_bytes = len(body)
        await session.commit()
        return node.id


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
async def test_reference_video_pipeline_reuses_one_governed_image_for_all_provider_scenes() -> None:
    scope = await seed_scope("reference")
    try:
        reference_id = await seed_reference_node(scope)
        req = video_request(
            operation="logo-to-video", reference_count=1, use_case="logo-animation"
        )
        async with SessionLocal() as session:
            pipeline = await create_routed_video_pipeline(
                session,
                scope=scope.media_scope(),
                request=req,
                runtime_evidence=evidence(operation="logo-to-video"),
                idempotency_key="p36f-reference",
                reference_node_id=reference_id,
            )
            await session.commit()
        assert pipeline.reference_node_id is not None
        assert len(pipeline.execution_ids) == 4
        async with SessionLocal() as session:
            executions = list(
                (
                    await session.scalars(
                        select(VideoExecution).where(VideoExecution.graph_id == pipeline.graph_id)
                    )
                ).all()
            )
            nodes = list(
                (
                    await session.scalars(
                        select(MediaAssetNode).where(MediaAssetNode.graph_id == pipeline.graph_id)
                    )
                ).all()
            )
            edges = list(
                (
                    await session.scalars(
                        select(MediaAssetEdge).where(MediaAssetEdge.graph_id == pipeline.graph_id)
                    )
                ).all()
            )
            steps = list(
                (
                    await session.scalars(
                        select(MediaRenderStep).where(MediaRenderStep.graph_id == pipeline.graph_id)
                    )
                ).all()
            )
        reference = next(node for node in nodes if node.logical_key == "reference-00")
        assert reference.id == pipeline.reference_node_id
        assert reference.status == "completed" and reference.storage_key and reference.checksum
        assert all(row.operation == "logo-to-video" for row in executions)
        assert all((row.request_options or {}).get("reference_count") == 1 for row in executions)
        provider_ids = {row.target_node_id for row in executions}
        reference_edges = [
            edge for edge in edges
            if edge.parent_node_id == reference.id and edge.child_node_id in provider_ids
        ]
        assert len(reference_edges) == 4
        assert len(steps) == 1 and steps[0].operation == "assemble"
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_reference_video_pipeline_fails_before_graph_without_governed_reference() -> None:
    scope = await seed_scope("reference-missing")
    try:
        req = video_request(operation="image-to-video", reference_count=1)
        async with SessionLocal() as session:
            before = int(await session.scalar(select(func.count()).select_from(VideoExecution)) or 0)
            with pytest.raises(VideoPipelineError, match="exactly one governed input"):
                await create_routed_video_pipeline(
                    session,
                    scope=scope.media_scope(),
                    request=req,
                    runtime_evidence=evidence(operation="image-to-video"),
                    idempotency_key="p36f-reference-missing",
                )
            await session.rollback()
        async with SessionLocal() as session:
            after = int(await session.scalar(select(func.count()).select_from(VideoExecution)) or 0)
            assert after == before
    finally:
        await cleanup(scope)

@pytest.mark.asyncio
async def test_video_worker_loads_governed_reference_bytes_and_rejects_storage_corruption(
    tmp_path,
) -> None:
    scope = await seed_scope("worker-reference")
    platform_id = settings.PROJECT_AI_PLATFORM_PROVIDER_ORGANIZATION_ID
    created_platform = False
    provider_id: str | None = None
    store = LocalMediaObjectStore(tmp_path / "objects")
    body = b"governed-reference-image-bytes"
    try:
        async with SessionLocal() as session:
            platform = await session.get(Organization, platform_id)
            if platform is None:
                platform = Organization(
                    id=platform_id,
                    name="AIONEX Platform Providers",
                    slug=f"p36f-platform-{uuid4().hex[:8]}",
                    plan="enterprise",
                    status="active",
                )
                session.add(platform)
                await session.flush()
                created_platform = True
            provider = AIProvider(
                organization_id=platform_id,
                name="OpenAI",
                type="openai",
                status="connected",
                encrypted_api_key=encrypt_provider_secret("fake-provider-credential"),
                base_url="https://api.openai.com",
                config={"enabled": True},
            )
            session.add(provider)
            await session.flush()
            provider_id = provider.id
            await session.commit()

        reference_id = await seed_reference_node(scope, store=store, body=body)
        req = video_request(operation="image-to-video", reference_count=1)
        async with SessionLocal() as session:
            pipeline = await create_routed_video_pipeline(
                session,
                scope=scope.media_scope(),
                request=req,
                runtime_evidence=evidence(operation="image-to-video"),
                idempotency_key="p36f-worker-reference",
                reference_node_id=reference_id,
            )
            await arm_video_execution(
                session,
                execution_id=pipeline.execution_ids[0],
                organization_id=scope.org.id,
            )
            await session.commit()

        authority = VideoExecutionAuthority(
            store=store, worker_id="p36f-reference-worker", lease_seconds=30
        )
        claim = await authority.claim()
        assert claim is not None and claim.mode == "submit"
        worker = VideoProviderWorker(
            authority=authority, store=store, worker_id="p36f-reference-worker"
        )
        loaded = await worker._load_execution(claim)
        assert loaded.request.operation == "image-to-video"
        assert loaded.request.reference is not None
        assert loaded.request.reference.body == body
        assert loaded.request.reference.content_type == "image/png"
        assert loaded.request.reference.filename.endswith(".png")

        async with SessionLocal() as session:
            execution = await session.get(VideoExecution, claim.execution_id)
            assert execution is not None
            ref = await session.scalar(
                select(MediaAssetNode)
                .join(MediaAssetEdge, MediaAssetEdge.parent_node_id == MediaAssetNode.id)
                .where(MediaAssetEdge.child_node_id == execution.target_node_id)
            )
            assert ref is not None and ref.storage_key
            storage_key = ref.storage_key
        store.put_bytes(storage_key, b"X" * len(body), "image/png")
        with pytest.raises(ProviderVideoFailure) as captured:
            await worker._load_execution(claim)
        assert captured.value.code == "provider_input_integrity"
    finally:
        await cleanup(scope)
        async with SessionLocal() as session:
            if provider_id is not None:
                provider = await session.get(AIProvider, provider_id)
                if provider is not None:
                    await session.delete(provider)
                    await session.flush()
            if created_platform:
                platform = await session.get(Organization, platform_id)
                if platform is not None:
                    await session.delete(platform)
            await session.commit()

@pytest.mark.asyncio
async def test_reference_video_pipeline_rejects_cross_tenant_reference_before_execution() -> None:
    owner = await seed_scope("reference-owner")
    foreign = await seed_scope("reference-foreign")
    try:
        foreign_reference_id = await seed_reference_node(foreign)
        req = video_request(operation="logo-to-video", reference_count=1, use_case="logo-animation")
        async with SessionLocal() as session:
            before = int(await session.scalar(select(func.count()).select_from(VideoExecution)) or 0)
            with pytest.raises(VideoPipelineError, match="reference input is unavailable"):
                await create_routed_video_pipeline(
                    session,
                    scope=owner.media_scope(),
                    request=req,
                    runtime_evidence=evidence(operation="logo-to-video"),
                    idempotency_key="p36f-cross-tenant-reference",
                    reference_node_id=foreign_reference_id,
                )
            await session.rollback()
        async with SessionLocal() as session:
            after = int(await session.scalar(select(func.count()).select_from(VideoExecution)) or 0)
            assert after == before
    finally:
        await cleanup(owner)
        await cleanup(foreign)
