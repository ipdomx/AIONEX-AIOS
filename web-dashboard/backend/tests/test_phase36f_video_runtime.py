"""Phase 36F durable asynchronous video authority without provider HTTP."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    MediaAssetGraph,
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
from app.services.media_graph_runtime import MediaGraphScope, create_media_graph, media_graph_snapshot
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec
from app.services.media_storage import LocalMediaObjectStore
from app.services.video_runtime import (
    VideoExecutionAuthority,
    VideoExecutionError,
    VideoExecutionSpec,
    VideoLeaseLost,
    arm_video_execution,
    create_video_execution,
)

# Minimal governed envelope used only for authority/storage tests. FFmpeg/ffprobe QA belongs to worker acceptance.
_MP4_ENVELOPE = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41"


class Scope:
    def __init__(
        self,
        org: Organization,
        user: User,
        workspace: Workspace,
        project: Project,
        job: StudioJob,
        asset: StudioAsset,
    ) -> None:
        self.org = org
        self.user = user
        self.workspace = workspace
        self.project = project
        self.job = job
        self.asset = asset


async def seed_scope(tag: str) -> Scope:
    suffix = uuid4().hex[:10]
    async with SessionLocal() as session:
        org = Organization(
            name=f"P36F {tag}", slug=f"p36f-{tag}-{suffix}", plan="enterprise", status="active"
        )
        session.add(org)
        await session.flush()
        user = User(
            organization_id=org.id,
            role_id=None,
            email=f"p36f-{tag}-{suffix}@example.com",
            name="Phase36F Owner",
            password_hash="unused",
            status="active",
        )
        workspace = Workspace(
            organization_id=org.id,
            name="P36F Workspace",
            slug=f"p36f-ws-{suffix}",
            status="active",
        )
        session.add_all([user, workspace])
        await session.flush()
        project = Project(
            organization_id=org.id,
            workspace_id=workspace.id,
            owner_id=user.id,
            name="P36F Video Project",
            slug=f"p36f-project-{suffix}",
            description="Durable asynchronous provider video execution acceptance.",
            status="active",
            priority="high",
            progress=10,
        )
        session.add(project)
        await session.flush()
        job = StudioJob(
            organization_id=org.id,
            workspace_id=workspace.id,
            project_id=project.id,
            requested_by_id=user.id,
            department="video",
            output_kind="video",
            title="P36F Video",
            brief="Create a governed multi-scene provider video.",
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
            title="P36F Video",
            filename="phase36f-plan.zip",
            media_type="application/zip",
            storage_path="/tmp/p36f-plan.zip",
            checksum="a" * 64,
            size_bytes=1,
            status="active",
            current_revision=1,
            asset_metadata={"render_status": "planned"},
        )
        session.add(asset)
        await session.commit()
        return Scope(org, user, workspace, project, job, asset)


async def cleanup_scope(scope: Scope) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id == scope.org.id))
        await session.commit()


async def create_video_graph(scope: Scope) -> tuple[str, str, str]:
    spec = MediaGraphSpec(
        title="P36F async provider scene",
        asset_kind="video",
        nodes=(
            MediaNodeSpec(
                key="scene-001-opening",
                node_type="video-provider-scene",
                media_type="video/mp4",
                prompt_metadata={"private_prompt": "must-not-leak"},
                parameters={"executor": "video-provider"},
                scene_metadata={"scene_id": "opening", "continuity_id": "vid-test"},
                timeline_metadata={"duration_seconds": 4, "ordinal": 0},
            ),
            MediaNodeSpec(
                key="assembly",
                node_type="assembly",
                media_type="video/mp4",
                parameters={
                    "operation": "assemble",
                    "output_profile": "video-mp4-h264",
                    "hardware_adapter": "software",
                },
                timeline_metadata={"scene_count": 1},
            ),
        ),
        edges=(MediaEdgeSpec("scene-001-opening", "assembly", ordinal=0),),
        output_profile="video-mp4-h264",
        provenance=({"type": "phase36f-test"},),
    )
    async with SessionLocal() as session:
        graph = await create_media_graph(
            session,
            scope=MediaGraphScope(
                organization_id=scope.org.id,
                created_by_id=scope.user.id,
                workspace_id=scope.workspace.id,
                project_id=scope.project.id,
                studio_job_id=scope.job.id,
                studio_asset_id=scope.asset.id,
            ),
            spec=spec,
            idempotency_key=f"video-graph-{uuid4()}",
        )
        scene = await session.scalar(
            select(MediaAssetNode).where(
                MediaAssetNode.graph_id == graph.id,
                MediaAssetNode.logical_key == "scene-001-opening",
            )
        )
        assembly = await session.scalar(
            select(MediaAssetNode).where(
                MediaAssetNode.graph_id == graph.id,
                MediaAssetNode.logical_key == "assembly",
            )
        )
        assert scene is not None and assembly is not None
        await session.commit()
        return graph.id, scene.id, assembly.id


async def create_execution(
    scope: Scope,
    graph_id: str,
    target_node_id: str,
    *,
    key: str | None = None,
    max_attempts: int = 3,
    max_polls: int = 20,
) -> str:
    async with SessionLocal() as session:
        row = await create_video_execution(
            session,
            spec=VideoExecutionSpec(
                organization_id=scope.org.id,
                requested_by_id=scope.user.id,
                workspace_id=scope.workspace.id,
                project_id=scope.project.id,
                studio_job_id=scope.job.id,
                studio_asset_id=scope.asset.id,
                graph_id=graph_id,
                target_node_id=target_node_id,
                scene_key="opening",
                provider="openai",
                model="sora-2",
                operation="text-to-video",
                prompt="Create a four-second governed opening scene for the AIONEX launch film.",
                idempotency_key=key or f"video-execution-{uuid4()}",
                request_options={
                    "seconds": 4,
                    "size": "1280x720",
                    "resolution": "720p",
                    "reference_count": 0,
                },
                output_format="mp4",
                estimated_cost_usd=0.10,
                max_attempts=max_attempts,
                max_polls=max_polls,
            ),
        )
        await session.commit()
        return row.id


async def make_available(execution_id: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(VideoExecution, execution_id)
        assert row is not None
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


@pytest.mark.asyncio
async def test_video_execution_is_planned_idempotent_and_fail_closed_until_arm(tmp_path: Path) -> None:
    scope = await seed_scope("arm")
    try:
        graph_id, scene_id, _ = await create_video_graph(scope)
        execution_id = await create_execution(scope, graph_id, scene_id, key="phase36f-arm-idempotency")
        duplicate_id = await create_execution(scope, graph_id, scene_id, key="phase36f-arm-idempotency")
        assert duplicate_id == execution_id
        authority = VideoExecutionAuthority(
            store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="video-worker-a"
        )
        assert await authority.claim() is None
        async with SessionLocal() as session:
            ffmpeg_steps = list(
                (
                    await session.scalars(
                        select(MediaRenderStep).where(MediaRenderStep.graph_id == graph_id)
                    )
                ).all()
            )
            assert len(ffmpeg_steps) == 1
            assert ffmpeg_steps[0].operation == "assemble" and ffmpeg_steps[0].status == "planned"
            row = await arm_video_execution(
                session, execution_id=execution_id, organization_id=scope.org.id
            )
            assert row.status == "queued" and row.armed_at is not None
            assert row.provider_job_id is None and row.actual_cost_usd is None
            await session.commit()
        claim = await authority.claim()
        assert claim is not None and claim.execution_id == execution_id and claim.fencing_token == 1 and claim.mode == "submit"
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            assert row is not None
            assert row.status == "running" and row.attempts == 1 and row.poll_count == 0
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_provider_job_survives_requeue_and_poll_does_not_resubmit(tmp_path: Path) -> None:
    scope = await seed_scope("poll")
    try:
        graph_id, scene_id, _ = await create_video_graph(scope)
        execution_id = await create_execution(scope, graph_id, scene_id)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        authority = VideoExecutionAuthority(
            store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="video-worker-a"
        )
        submission = await authority.claim()
        assert submission is not None and submission.mode == "submit"
        await authority.mark_submission_started(submission)
        await authority.record_provider_job(
            submission,
            provider_job_id="video-job-123",
            provider_state="queued",
            progress=0,
            provider_response_metadata={
                "request_id": "req-safe",
                "prompt": "must-not-persist",
                "signed_url": "https://must-not-persist.example/token",
            },
            poll_after_seconds=1,
        )
        await make_available(execution_id)
        poll_claim = await authority.claim()
        assert poll_claim is not None and poll_claim.fencing_token == 2 and poll_claim.mode == "poll" and poll_claim.provider_job_id == "video-job-123"
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            assert row is not None
            assert row.provider_job_id == "video-job-123"
            assert row.attempts == 1
            assert row.poll_count == 1
            assert row.provider_state == "queued"
            assert row.provider_response_metadata["request_id"] == "req-safe"
            assert "prompt" not in row.provider_response_metadata
            assert "signed_url" not in row.provider_response_metadata
        await authority.record_poll_pending(
            poll_claim,
            provider_state="in_progress",
            progress=42,
            provider_response_metadata={"status_code": 200, "api_token": "must-not-persist"},
            poll_after_seconds=1,
        )
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            assert row is not None
            assert row.status == "queued" and row.provider_state == "in_progress"
            assert row.provider_progress == 42 and row.attempts == 1 and row.poll_count == 1
            assert "api_token" not in row.provider_response_metadata
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_crash_after_submission_marker_reclaims_as_reconcile_not_resubmit(tmp_path: Path) -> None:
    scope = await seed_scope("ambiguous-submit")
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker_a = VideoExecutionAuthority(store=store, worker_id="video-worker-a", lease_seconds=30)
    worker_b = VideoExecutionAuthority(store=store, worker_id="video-worker-b", lease_seconds=30)
    try:
        graph_id, scene_id, _ = await create_video_graph(scope)
        execution_id = await create_execution(scope, graph_id, scene_id, max_attempts=1, max_polls=3)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        submit = await worker_a.claim()
        assert submit is not None and submit.mode == "submit"
        await worker_a.mark_submission_started(submit)
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            assert row is not None
            assert row.provider_state == "submitting" and row.provider_job_id is None
            assert row.attempts == 1 and row.poll_count == 0
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        reconcile = await worker_b.claim()
        assert reconcile is not None
        assert reconcile.mode == "reconcile" and reconcile.provider_job_id is None
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            assert row is not None
            assert row.attempts == 1 and row.poll_count == 1
            assert row.provider_state == "submitting"
        # A reconciler may adopt the uniquely discovered provider job; it must not issue a second submit.
        await worker_b.record_provider_job(
            reconcile,
            provider_job_id="video-job-reconciled",
            provider_state="in_progress",
            provider_response_metadata={"reconciled": True},
            poll_after_seconds=1,
        )
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            assert row is not None
            assert row.provider_job_id == "video-job-reconciled"
            assert row.attempts == 1 and row.poll_count == 1
            assert row.status == "queued"
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_definitive_submission_rejection_can_reopen_only_bounded_submit_budget(tmp_path: Path) -> None:
    scope = await seed_scope("definitive-reject")
    authority = VideoExecutionAuthority(
        store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="video-worker-a"
    )
    try:
        graph_id, scene_id, _ = await create_video_graph(scope)
        execution_id = await create_execution(scope, graph_id, scene_id, max_attempts=2)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        first = await authority.claim()
        assert first is not None and first.mode == "submit"
        await authority.mark_submission_started(first)
        await authority.fail(
            first,
            code="provider_rejected_before_job",
            message="Provider definitively rejected the request before creating a job",
            submission_safe_to_retry=True,
            retry_after_seconds=1,
        )
        await make_available(execution_id)
        second = await authority.claim()
        assert second is not None and second.mode == "submit"
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            assert row is not None
            assert row.attempts == 2 and row.poll_count == 0
            assert row.provider_state == "not_started" and row.provider_job_id is None
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_reclaimed_video_lease_rejects_stale_worker_without_duplicate_submission(tmp_path: Path) -> None:
    scope = await seed_scope("fencing")
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker_a = VideoExecutionAuthority(store=store, worker_id="video-worker-a", lease_seconds=30)
    worker_b = VideoExecutionAuthority(store=store, worker_id="video-worker-b", lease_seconds=30)
    try:
        graph_id, scene_id, _ = await create_video_graph(scope)
        execution_id = await create_execution(scope, graph_id, scene_id)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        first = await worker_a.claim()
        assert first is not None and first.fencing_token == 1
        await worker_a.mark_submission_started(first)
        await worker_a.record_provider_job(
            first,
            provider_job_id="video-job-fenced",
            provider_state="in_progress",
            provider_response_metadata={},
            poll_after_seconds=1,
        )
        await make_available(execution_id)
        stale = await worker_a.claim()
        assert stale is not None and stale.fencing_token == 2
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            assert row is not None
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        current = await worker_b.claim()
        assert current is not None and current.fencing_token == 3
        with pytest.raises(VideoLeaseLost):
            await worker_a.record_poll_pending(
                stale,
                provider_state="in_progress",
                provider_response_metadata={},
            )
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            assert row is not None
            assert row.provider_job_id == "video-job-fenced"
            assert row.attempts == 1
            assert row.poll_count == 2
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_completed_provider_scene_unblocks_only_downstream_assembly_and_hides_private_evidence(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("complete")
    store = LocalMediaObjectStore(tmp_path / "objects")
    authority = VideoExecutionAuthority(store=store, worker_id="video-worker-a")
    try:
        graph_id, scene_id, assembly_id = await create_video_graph(scope)
        execution_id = await create_execution(scope, graph_id, scene_id)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        submit = await authority.claim()
        assert submit is not None
        await authority.mark_submission_started(submit)
        await authority.record_provider_job(
            submit,
            provider_job_id="video-job-complete",
            provider_state="in_progress",
            provider_response_metadata={"request_id": "provider-request-safe"},
            poll_after_seconds=1,
        )
        await make_available(execution_id)
        poll = await authority.claim()
        assert poll is not None
        result = await authority.complete_bytes(
            poll,
            body=_MP4_ENVELOPE,
            content_type="video/mp4",
            provider_response_metadata={
                "finish_reason": "completed",
                "prompt": "must-not-persist",
                "download_url": "https://must-not-persist.example/file",
            },
            usage_metadata={"seconds": 4, "api_token": "must-not-persist"},
            actual_cost_usd=0.08,
            cost_basis="official_provider_usage",
        )
        assert result["graph_pending_nodes"] == 1
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            scene = await session.get(MediaAssetNode, scene_id)
            assembly = await session.get(MediaAssetNode, assembly_id)
            graph = await session.get(MediaAssetGraph, graph_id)
            steps = list(
                (
                    await session.scalars(
                        select(MediaRenderStep).where(MediaRenderStep.graph_id == graph_id)
                    )
                ).all()
            )
            audit_count = int(
                await session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.resource_type == "video_execution",
                        AuditEvent.resource_id == execution_id,
                        AuditEvent.action == "video.provider.completed",
                    )
                )
                or 0
            )
            assert row is not None and row.status == "completed"
            assert row.provider_job_id == "video-job-complete" and row.provider_state == "completed"
            assert row.output_checksum == scene.checksum and row.output_size_bytes == len(_MP4_ENVELOPE)
            assert row.actual_cost_usd == pytest.approx(0.08)
            assert "prompt" not in row.provider_response_metadata
            assert "download_url" not in row.provider_response_metadata
            assert "api_token" not in row.usage_metadata
            assert scene is not None and scene.status == "completed"
            assert scene.media_type == "video/mp4" and scene.storage_key and scene.checksum
            assert assembly is not None and assembly.status == "planned"
            assert graph is not None and graph.status == "rendering"
            assert len(steps) == 1 and steps[0].target_node_id == assembly_id and steps[0].status == "planned"
            assert audit_count == 1
            public = await media_graph_snapshot(session, graph)
            rendered = repr(public)
            assert "video-job-complete" not in rendered
            assert "must-not-leak" not in rendered
            assert "compiled_prompt" not in rendered
            assert "must-not-persist" not in rendered
            assert scene.storage_key not in rendered
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_invalid_mp4_is_rejected_before_storage_commit(tmp_path: Path) -> None:
    scope = await seed_scope("invalid")
    store = LocalMediaObjectStore(tmp_path / "objects")
    authority = VideoExecutionAuthority(store=store, worker_id="video-worker-a")
    try:
        graph_id, scene_id, _ = await create_video_graph(scope)
        execution_id = await create_execution(scope, graph_id, scene_id)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        submit = await authority.claim()
        assert submit is not None
        await authority.mark_submission_started(submit)
        await authority.record_provider_job(
            submit,
            provider_job_id="video-job-invalid",
            provider_state="in_progress",
            provider_response_metadata={},
            poll_after_seconds=1,
        )
        await make_available(execution_id)
        poll = await authority.claim()
        assert poll is not None
        with pytest.raises(VideoExecutionError, match="invalid MP4"):
            await authority.complete_bytes(
                poll,
                body=b"not-a-video",
                content_type="video/mp4",
                provider_response_metadata={},
                usage_metadata={},
                actual_cost_usd=None,
            )
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, execution_id)
            node = await session.get(MediaAssetNode, scene_id)
            assert row is not None and row.status == "running"
            assert node is not None and node.status == "planned" and node.storage_key is None
        assert not any(path.is_file() for path in (tmp_path / "objects").rglob("*") if path.name != ".media-storage-preflight")
    finally:
        await cleanup_scope(scope)


def test_video_execution_schema_has_async_job_fencing_poll_and_cost_evidence() -> None:
    from app.db.base import Base
    import app.db.models  # noqa: F401

    columns = set(Base.metadata.tables["video_executions"].c.keys())
    assert {
        "status",
        "armed_at",
        "lease_token",
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "provider_job_id",
        "provider_state",
        "provider_progress",
        "provider_submitted_at",
        "last_polled_at",
        "attempts",
        "max_attempts",
        "poll_count",
        "max_polls",
        "estimated_cost_usd",
        "actual_cost_usd",
        "cost_basis",
        "output_storage_key",
        "output_checksum",
        "usage_metadata",
        "provider_response_metadata",
    } <= columns
