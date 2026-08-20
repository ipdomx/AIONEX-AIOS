"""Phase 36F durable video execution authority without live provider calls."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from aios.video_factory import VideoRequest, build_video_plan
from app.db.base import SessionLocal
from app.db.models import (
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    Organization,
    Project,
    StudioAsset,
    StudioJob,
    User,
    VideoExecution,
    VideoSceneExecution,
    Workspace,
)
from app.services.media_storage import LocalMediaObjectStore
from app.services.video_execution_runtime import (
    VideoExecutionError,
    VideoExecutionSpec,
    VideoSceneExecutionAuthority,
    VideoSceneLeaseLost,
    arm_video_execution,
    create_video_execution,
    finalize_assembled_execution,
    resume_failed_video_execution,
)


def fake_mp4(tag: str) -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + tag.encode("utf-8")


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
            description="Durable multi-scene video execution acceptance.",
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
            brief="Create a governed multi-scene product launch film.",
            language="en-US",
            style="modern cinematic",
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
            filename="planned-video.zip",
            media_type="application/zip",
            storage_path="/tmp/p36f-planned-video.zip",
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


def plan():
    return build_video_plan(
        VideoRequest(
            title="AIONEX launch film",
            brief=(
                "Create a concise premium launch film with private-marker-36f in the brief, "
                "a truthful value sequence, proof scene, and call to action."
            ),
            operation="text-to-video",
            use_case="advertisement",
            resolution="720p",
            style="modern cinematic",
            target_audience="technology founders",
            brand_name="AIONEX",
            exact_text=("AIONEX",),
        )
    )


async def create_execution(
    scope: Scope, *, key: str | None = None, max_attempts: int = 3, max_polls: int = 360
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
                plan=plan(),
                idempotency_key=key or f"video-{uuid4()}",
                estimated_cost_usd=0.08,
                max_attempts=max_attempts,
                max_polls=max_polls,
            ),
        )
        await session.commit()
        return row.id


async def make_scene_available(scene_execution_id: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(VideoSceneExecution, scene_execution_id)
        assert row is not None
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


async def submit_and_poll_claim(
    authority: VideoSceneExecutionAuthority,
    submit_claim,
    *,
    provider_request_id: str,
    provider_response_metadata: dict | None = None,
):
    assert submit_claim.mode == "submit"
    await authority.mark_submission_started(submit_claim)
    await authority.record_provider_request(
        submit_claim,
        provider_request_id=provider_request_id,
        provider_state="queued",
        provider_response_metadata=provider_response_metadata or {},
        progress=0,
        poll_after_seconds=1,
    )
    await make_scene_available(submit_claim.scene_execution_id)
    poll_claim = await authority.claim()
    assert poll_claim is not None
    assert poll_claim.scene_execution_id == submit_claim.scene_execution_id
    assert poll_claim.mode == "poll"
    assert poll_claim.provider_request_id == provider_request_id
    return poll_claim


@pytest.mark.asyncio
async def test_video_execution_is_fail_closed_until_arm_and_creates_only_assembly_ffmpeg_step(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("arm")
    try:
        execution_id = await create_execution(scope, key="phase36f-video-arm-idempotency")
        duplicate_id = await create_execution(scope, key="phase36f-video-arm-idempotency")
        assert duplicate_id == execution_id
        authority = VideoSceneExecutionAuthority(
            store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="video-worker-a"
        )
        assert await authority.claim() is None
        async with SessionLocal() as session:
            parent = await session.get(VideoExecution, execution_id)
            assert parent is not None and parent.status == "planned"
            assert "private-marker-36f" not in repr(parent.plan_metadata)
            scenes = list(
                (
                    await session.scalars(
                        select(VideoSceneExecution)
                        .where(VideoSceneExecution.video_execution_id == execution_id)
                        .order_by(VideoSceneExecution.scene_index)
                    )
                ).all()
            )
            assert len(scenes) == 4
            assert all(item.status == "planned" for item in scenes)
            ffmpeg_steps = int(
                await session.scalar(
                    select(func.count(MediaRenderStep.id)).where(
                        MediaRenderStep.graph_id == parent.graph_id
                    )
                )
                or 0
            )
            assert ffmpeg_steps == 1
            step = await session.scalar(
                select(MediaRenderStep).where(MediaRenderStep.graph_id == parent.graph_id)
            )
            assert step is not None and step.operation == "assemble" and step.engine == "ffmpeg"
            nodes = list(
                (
                    await session.scalars(
                        select(MediaAssetNode)
                        .where(MediaAssetNode.graph_id == parent.graph_id)
                        .order_by(MediaAssetNode.logical_key)
                    )
                ).all()
            )
            assert sum(item.node_type == "provider-video" for item in nodes) == 4
            await arm_video_execution(
                session, execution_id=execution_id, organization_id=scope.org.id
            )
            await session.commit()
        claim = await authority.claim()
        assert claim is not None and claim.video_execution_id == execution_id
        async with SessionLocal() as session:
            claimed = await session.get(VideoSceneExecution, claim.scene_execution_id)
            assert claimed is not None and claimed.scene_index == 0 and claimed.fencing_token == 1
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_scene_lease_recovery_preserves_provider_job_and_fences_stale_worker(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("lease")
    try:
        execution_id = await create_execution(scope)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        store = LocalMediaObjectStore(tmp_path / "objects")
        first = VideoSceneExecutionAuthority(store=store, worker_id="video-worker-a", lease_seconds=30)
        submit = await first.claim()
        assert submit is not None and submit.mode == "submit"
        poll1 = await submit_and_poll_claim(
            first,
            submit,
            provider_request_id="provider-job-001",
            provider_response_metadata={"status": "queued", "api_key": "must-not-store"},
        )
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, poll1.scene_execution_id)
            assert row is not None
            assert row.provider_request_id == "provider-job-001"
            assert row.attempts == 1 and row.poll_count == 1
            assert "api_key" not in row.provider_response_metadata
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        second = VideoSceneExecutionAuthority(store=store, worker_id="video-worker-b", lease_seconds=30)
        poll2 = await second.claim()
        assert poll2 is not None and poll2.mode == "poll"
        assert poll2.scene_execution_id == poll1.scene_execution_id
        assert poll2.fencing_token == poll1.fencing_token + 1
        assert poll2.provider_request_id == "provider-job-001"
        with pytest.raises(VideoSceneLeaseLost):
            await first.complete_scene_bytes(
                poll1,
                body=fake_mp4("stale"),
                content_type="video/mp4",
                provider_response_metadata={},
                usage_metadata={},
                actual_cost_usd=0.01,
                cost_basis="official_fixed_video",
            )
        result = await second.complete_scene_bytes(
            poll2,
            body=fake_mp4("scene-one"),
            content_type="video/mp4",
            provider_response_metadata={"status": "completed"},
            usage_metadata={"seconds": 4},
            actual_cost_usd=0.01,
            cost_basis="official_fixed_video",
        )
        assert result["scene_status"] == "completed"
        next_claim = await second.claim()
        assert next_claim is not None and next_claim.mode == "submit"
        async with SessionLocal() as session:
            next_row = await session.get(VideoSceneExecution, next_claim.scene_execution_id)
            assert next_row is not None and next_row.scene_index == 1
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_permanent_scene_failure_and_resume_preserve_completed_scenes(tmp_path: Path) -> None:
    scope = await seed_scope("resume")
    try:
        execution_id = await create_execution(scope, max_attempts=1)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        authority = VideoSceneExecutionAuthority(
            store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="video-worker-a"
        )
        first = await authority.claim()
        assert first is not None
        first_poll = await submit_and_poll_claim(
            authority, first, provider_request_id="job-complete"
        )
        await authority.complete_scene_bytes(
            first_poll,
            body=fake_mp4("completed-scene"),
            content_type="video/mp4",
            provider_response_metadata={},
            usage_metadata={},
            actual_cost_usd=0.01,
            cost_basis="official_fixed_video",
        )
        second = await authority.claim()
        assert second is not None
        await authority.fail(second, code="provider_failed", message="sanitized failure", permanent=True)
        async with SessionLocal() as session:
            parent = await session.get(VideoExecution, execution_id)
            assert parent is not None and parent.status == "failed"
            before = list(
                (
                    await session.scalars(
                        select(VideoSceneExecution)
                        .where(VideoSceneExecution.video_execution_id == execution_id)
                        .order_by(VideoSceneExecution.scene_index)
                    )
                ).all()
            )
            assert [item.status for item in before] == ["completed", "failed", "queued", "queued"]
            completed_checksum = before[0].output_checksum
            await resume_failed_video_execution(
                session, execution_id=execution_id, organization_id=scope.org.id
            )
            await session.commit()
        async with SessionLocal() as session:
            after = list(
                (
                    await session.scalars(
                        select(VideoSceneExecution)
                        .where(VideoSceneExecution.video_execution_id == execution_id)
                        .order_by(VideoSceneExecution.scene_index)
                    )
                ).all()
            )
            parent = await session.get(VideoExecution, execution_id)
            assert parent is not None and parent.status == "queued" and parent.resume_count == 1
            assert [item.status for item in after] == ["completed", "queued", "queued", "queued"]
            assert after[0].output_checksum == completed_checksum
            assert after[1].attempts == 0
        resumed = await authority.claim()
        assert resumed is not None
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, resumed.scene_execution_id)
            assert row is not None and row.scene_index == 1
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_all_scenes_complete_before_final_assembly_can_finalize(tmp_path: Path) -> None:
    scope = await seed_scope("finalize")
    try:
        execution_id = await create_execution(scope)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        authority = VideoSceneExecutionAuthority(
            store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="video-worker-a"
        )
        for index in range(4):
            claim = await authority.claim()
            assert claim is not None
            poll_claim = await submit_and_poll_claim(
                authority, claim, provider_request_id=f"provider-job-{index}"
            )
            await authority.complete_scene_bytes(
                poll_claim,
                body=fake_mp4(f"scene-{index}"),
                content_type="video/mp4",
                provider_response_metadata={"status": "completed"},
                usage_metadata={"seconds": 4 if index in {0, 3} else 8},
                actual_cost_usd=0.01,
                cost_basis="official_fixed_video",
            )
        assert await authority.claim() is None
        async with SessionLocal() as session:
            parent = await session.get(VideoExecution, execution_id)
            assert parent is not None
            assert parent.status == "scenes_completed"
            assert parent.actual_cost_usd == pytest.approx(0.04)
            assert parent.cost_basis == "official_fixed_video"
            with pytest.raises(VideoExecutionError, match="assembly is not complete"):
                await finalize_assembled_execution(
                    session, execution_id=execution_id, organization_id=scope.org.id
                )
            await session.rollback()
        async with SessionLocal() as session:
            parent = await session.get(VideoExecution, execution_id)
            assert parent is not None
            graph = await session.get(MediaAssetGraph, parent.graph_id)
            assembly = await session.scalar(
                select(MediaAssetNode).where(
                    MediaAssetNode.graph_id == parent.graph_id,
                    MediaAssetNode.logical_key == "assembly",
                )
            )
            assert graph is not None and assembly is not None
            graph.status = "completed"
            assembly.status = "completed"
            assembly.storage_backend = "local"
            assembly.storage_key = "final/final.mp4"
            assembly.checksum = "f" * 64
            assembly.size_bytes = 1234
            assembly.media_type = "video/mp4"
            await finalize_assembled_execution(
                session, execution_id=execution_id, organization_id=scope.org.id
            )
            await session.commit()
        async with SessionLocal() as session:
            parent = await session.get(VideoExecution, execution_id)
            assert parent is not None
            assert parent.status == "completed"
            assert parent.final_checksum == "f" * 64
            assert parent.final_storage_key == "final/final.mp4"
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_parent_cost_stays_unknown_when_any_completed_scene_lacks_cost(tmp_path: Path) -> None:
    scope = await seed_scope("cost-truth")
    try:
        execution_id = await create_execution(scope)
        async with SessionLocal() as session:
            await arm_video_execution(session, execution_id=execution_id, organization_id=scope.org.id)
            await session.commit()
        authority = VideoSceneExecutionAuthority(
            store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="video-worker-a"
        )
        for index in range(4):
            claim = await authority.claim()
            assert claim is not None
            poll_claim = await submit_and_poll_claim(
                authority, claim, provider_request_id=f"provider-cost-job-{index}"
            )
            await authority.complete_scene_bytes(
                poll_claim,
                body=fake_mp4(f"cost-scene-{index}"),
                content_type="video/mp4",
                provider_response_metadata={"status": "completed"},
                usage_metadata={"seconds": 4 if index in {0, 3} else 8},
                actual_cost_usd=None if index == 2 else 0.01,
                cost_basis="unknown" if index == 2 else "official_fixed_video",
            )
        async with SessionLocal() as session:
            parent = await session.get(VideoExecution, execution_id)
            assert parent is not None and parent.status == "scenes_completed"
            assert parent.actual_cost_usd is None
            assert parent.cost_basis == "unknown"
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_crash_after_scene_submission_marker_reclaims_as_reconcile_not_resubmit(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("ambiguous-submit")
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker_a = VideoSceneExecutionAuthority(store=store, worker_id="video-worker-a", lease_seconds=30)
    worker_b = VideoSceneExecutionAuthority(store=store, worker_id="video-worker-b", lease_seconds=30)
    try:
        execution_id = await create_execution(scope, max_attempts=1)
        async with SessionLocal() as session:
            await arm_video_execution(
                session, execution_id=execution_id, organization_id=scope.org.id
            )
            await session.commit()
        submit = await worker_a.claim()
        assert submit is not None and submit.mode == "submit"
        await worker_a.mark_submission_started(submit)
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, submit.scene_execution_id)
            assert row is not None
            assert row.provider_state == "submitting"
            assert row.provider_request_id is None
            assert row.attempts == 1 and row.poll_count == 0
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        reconcile = await worker_b.claim()
        assert reconcile is not None
        assert reconcile.scene_execution_id == submit.scene_execution_id
        assert reconcile.mode == "reconcile"
        assert reconcile.provider_request_id is None
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, reconcile.scene_execution_id)
            assert row is not None
            assert row.provider_state == "submitting"
            assert row.attempts == 1 and row.poll_count == 1
        await worker_b.record_provider_request(
            reconcile,
            provider_request_id="provider-job-reconciled",
            provider_state="in_progress",
            provider_response_metadata={"reconciled": True},
            progress=25,
            poll_after_seconds=1,
        )
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, reconcile.scene_execution_id)
            assert row is not None
            assert row.provider_request_id == "provider-job-reconciled"
            assert row.status == "queued"
            assert row.attempts == 1 and row.poll_count == 1
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_definitive_scene_submission_rejection_reopens_only_bounded_submit_budget(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("definitive-reject")
    authority = VideoSceneExecutionAuthority(
        store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="video-worker-a"
    )
    try:
        execution_id = await create_execution(scope, max_attempts=2)
        async with SessionLocal() as session:
            await arm_video_execution(
                session, execution_id=execution_id, organization_id=scope.org.id
            )
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
        await make_scene_available(first.scene_execution_id)
        second = await authority.claim()
        assert second is not None
        assert second.scene_execution_id == first.scene_execution_id
        assert second.mode == "submit"
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, second.scene_execution_id)
            assert row is not None
            assert row.attempts == 2 and row.poll_count == 0
            assert row.provider_state == "not_started"
            assert row.provider_request_id is None
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_exhausted_scene_reconcile_budget_dead_letters_parent(tmp_path: Path) -> None:
    scope = await seed_scope("dead-letter")
    authority = VideoSceneExecutionAuthority(
        store=LocalMediaObjectStore(tmp_path / "objects"), worker_id="video-worker-a", lease_seconds=30
    )
    try:
        execution_id = await create_execution(scope, max_attempts=1, max_polls=1)
        async with SessionLocal() as session:
            await arm_video_execution(
                session, execution_id=execution_id, organization_id=scope.org.id
            )
            await session.commit()
        submit = await authority.claim()
        assert submit is not None and submit.mode == "submit"
        await authority.mark_submission_started(submit)
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, submit.scene_execution_id)
            assert row is not None
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        reconcile = await authority.claim()
        assert reconcile is not None and reconcile.mode == "reconcile"
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, reconcile.scene_execution_id)
            assert row is not None and row.poll_count == 1
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        assert await authority.claim() is None
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, reconcile.scene_execution_id)
            parent = await session.get(VideoExecution, execution_id)
            assert row is not None and row.status == "failed"
            assert row.error_code == "video_scene_poll_exhausted"
            assert parent is not None and parent.status == "failed"
            assert parent.error_code == "video_scene_poll_exhausted"
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_invalid_scene_mp4_is_rejected_before_storage(tmp_path: Path) -> None:
    scope = await seed_scope("invalid-mp4")
    store = LocalMediaObjectStore(tmp_path / "objects")
    authority = VideoSceneExecutionAuthority(store=store, worker_id="video-worker-a")
    try:
        execution_id = await create_execution(scope)
        async with SessionLocal() as session:
            await arm_video_execution(
                session, execution_id=execution_id, organization_id=scope.org.id
            )
            await session.commit()
        submit = await authority.claim()
        assert submit is not None
        poll = await submit_and_poll_claim(
            authority, submit, provider_request_id="provider-job-invalid"
        )
        with pytest.raises(VideoExecutionError, match="recognizable MP4"):
            await authority.complete_scene_bytes(
                poll,
                body=b"not-a-video",
                content_type="video/mp4",
                provider_response_metadata={},
                usage_metadata={},
                actual_cost_usd=None,
            )
        async with SessionLocal() as session:
            row = await session.get(VideoSceneExecution, poll.scene_execution_id)
            node = await session.get(MediaAssetNode, row.target_node_id if row else "")
            assert row is not None and row.status == "running"
            assert node is not None and node.status == "planned" and node.storage_key is None
        root = tmp_path / "objects"
        assert not any(path.is_file() for path in root.rglob("*")) if root.exists() else True
    finally:
        await cleanup_scope(scope)


def test_video_scene_schema_contains_async_recovery_fields_only_on_scene_authority() -> None:
    from app.db.base import Base
    import app.db.models  # noqa: F401

    scene_columns = set(Base.metadata.tables["video_scene_executions"].c.keys())
    assert {
        "poll_count",
        "max_polls",
        "provider_state",
        "provider_progress",
        "provider_submitted_at",
        "last_polled_at",
    } <= scene_columns
    workflow_columns = set(Base.metadata.tables["workflow_runs"].c.keys())
    render_columns = set(Base.metadata.tables["media_render_steps"].c.keys())
    assert not {"provider_submitted_at", "last_polled_at"} & workflow_columns
    assert not {"poll_count", "max_polls"} & render_columns
