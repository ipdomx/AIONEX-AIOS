"""Phase 36F multi-scene project budget, recovery, resume, and assembly contracts."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from aios.video_factory import VideoRequest, VideoRuntimeEvidence
from app.core.config import settings
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
    Workspace,
)
from app.services.media_ffmpeg import MediaRenderResult, render_command_hash
from app.services.media_graph_runtime import MediaGraphScope
from app.services.media_render_worker import MediaRenderWorker
from app.services.media_storage import LocalMediaObjectStore
from app.services.video_pipeline import create_routed_video_pipeline
from app.services.video_project_runtime import (
    VideoProjectError,
    arm_video_project,
    create_failed_video_scene_recovery,
    video_project_snapshot,
)
from app.services.video_runtime import VideoExecutionAuthority

_MP4_ENVELOPE = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2mp41"


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


class FakeFFmpegRuntime:
    def preflight(self) -> dict[str, object]:
        return {"engine": "ffmpeg", "version": "9.0", "hardware_adapters": ["software"]}

    def render(
        self,
        *,
        operation: str,
        profile_id: str,
        input_paths: list[Path],
        output_path: Path,
        metadata: dict,
        input_checksums: list[str],
        hardware_adapter: str = "software",
    ) -> MediaRenderResult:
        content = json.dumps(
            {"operation": operation, "profile": profile_id, "metadata": metadata},
            sort_keys=True,
        ).encode()
        for path in input_paths:
            content += path.read_bytes()
        digest = hashlib.sha256(content).digest()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(digest * 8)
        return MediaRenderResult(
            output_path=output_path,
            command_hash=render_command_hash(
                operation=operation,
                profile_id=profile_id,
                metadata=metadata,
                input_checksums=input_checksums,
            ),
            probe={
                "streams": [
                    {"codec_type": "video", "codec_name": "h264", "width": 320, "height": 180},
                    {"codec_type": "audio", "codec_name": "aac", "sample_rate": "48000"},
                ],
                "format": {"duration": "4.000000", "format_name": "mov,mp4"},
            },
            engine_version="9.0",
            hardware_adapter=hardware_adapter,
        )


async def seed_scope(tag: str) -> Scope:
    suffix = uuid4().hex[:10]
    async with SessionLocal() as session:
        org = Organization(
            name=f"P36F {tag}",
            slug=f"p36f-project-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(org)
        await session.flush()
        user = User(
            organization_id=org.id,
            role_id=None,
            email=f"p36f-project-{tag}-{suffix}@example.invalid",
            name="P36F Project",
            password_hash="unused",
            status="active",
        )
        workspace = Workspace(
            organization_id=org.id,
            name="P36F Project",
            slug=f"p36f-project-ws-{suffix}",
            status="active",
        )
        session.add_all([user, workspace])
        await session.flush()
        project = Project(
            organization_id=org.id,
            workspace_id=workspace.id,
            owner_id=user.id,
            name="P36F Multi-scene",
            slug=f"p36f-project-{suffix}",
            description="No-provider multi-scene exit-gate acceptance.",
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
            title="P36F Multi-scene",
            brief="Create a governed multi-scene advertisement.",
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
            title="P36F Multi-scene",
            filename="planned.zip",
            media_type="application/zip",
            storage_path="/tmp/p36f-multiscene-planned.zip",
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


async def create_pipeline(scope: Scope):
    request = VideoRequest(
        title="AIONEX multi-scene launch film",
        brief="Create a real four-scene cinematic advertisement with continuity and truthful claims.",
        operation="text-to-video",
        use_case="advertisement",
        aspect_ratio="16:9",
        resolution="720p",
        style="cinematic",
        target_audience="general",
        reference_count=0,
        brand_name="AIONEX",
    )
    evidence = (
        VideoRuntimeEvidence(
            provider="openai",
            model="sora-2",
            state="ready",
            proven_operations=frozenset({"text-to-video"}),
            reason="source-only multi-scene coordination acceptance",
        ),
    )
    async with SessionLocal() as session:
        routed = await create_routed_video_pipeline(
            session,
            scope=scope.media_scope(),
            request=request,
            runtime_evidence=evidence,
            idempotency_key=f"p36f-multiscene-{uuid4()}",
        )
        await session.commit()
        return routed


async def execution_rows(graph_id: str) -> list[VideoExecution]:
    async with SessionLocal() as session:
        return list(
            (
                await session.scalars(
                    select(VideoExecution)
                    .where(VideoExecution.graph_id == graph_id)
                    .order_by(VideoExecution.created_at, VideoExecution.id)
                )
            ).all()
        )


async def make_available(execution_id: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(VideoExecution, execution_id)
        assert row is not None
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


async def complete_next_scene(
    authority: VideoExecutionAuthority,
    *,
    terminal_failure: bool = False,
) -> tuple[str, str, float]:
    submit = await authority.claim()
    assert submit is not None and submit.mode == "submit"
    async with SessionLocal() as session:
        row = await session.get(VideoExecution, submit.execution_id)
        assert row is not None
        scene_key = row.scene_key
        estimated = float(row.estimated_cost_usd or 0.0)
    await authority.mark_submission_started(submit)
    job_id = f"synthetic-{scene_key}-{uuid4().hex[:8]}"
    if terminal_failure:
        await authority.record_provider_job_failure(
            submit,
            provider_job_id=job_id,
            code="synthetic_terminal_failure",
            message="Synthetic terminal provider failure",
            provider_response_metadata={"synthetic": True},
        )
        return submit.execution_id, scene_key, estimated
    await authority.record_provider_job(
        submit,
        provider_job_id=job_id,
        provider_state="in_progress",
        provider_response_metadata={"synthetic": True},
        poll_after_seconds=1,
    )
    await make_available(submit.execution_id)
    poll = await authority.claim()
    assert poll is not None and poll.execution_id == submit.execution_id and poll.mode == "poll"
    await authority.complete_bytes(
        poll,
        body=_MP4_ENVELOPE + scene_key.encode("utf-8"),
        content_type="video/mp4",
        provider_response_metadata={"synthetic": True, "state": "completed"},
        usage_metadata={"seconds": 4},
        actual_cost_usd=estimated,
        cost_basis="official_fixed_second",
    )
    return submit.execution_id, scene_key, estimated


@pytest.mark.asyncio
async def test_project_arm_fails_closed_below_budget_then_arms_all_scenes_without_provider_http() -> None:
    scope = await seed_scope("budget")
    try:
        routed = await create_pipeline(scope)
        rows = await execution_rows(routed.graph_id)
        total = sum(float(row.estimated_cost_usd or 0.0) for row in rows)
        assert len(rows) == 4 and total == pytest.approx(2.4)
        async with SessionLocal() as session:
            with pytest.raises(VideoProjectError, match="cost cap"):
                await arm_video_project(
                    session,
                    organization_id=scope.org.id,
                    graph_id=routed.graph_id,
                    max_total_cost_usd=total - 0.01,
                )
            await session.rollback()
        assert all(row.status == "planned" and row.attempts == 0 for row in await execution_rows(routed.graph_id))
        async with SessionLocal() as session:
            armed = await arm_video_project(
                session,
                organization_id=scope.org.id,
                graph_id=routed.graph_id,
                max_total_cost_usd=total,
            )
            await session.commit()
        assert len(armed.armed_execution_ids) == 4
        assert armed.projected_cost_usd == pytest.approx(total)
        async with SessionLocal() as session:
            snapshot = await video_project_snapshot(
                session,
                organization_id=scope.org.id,
                graph_id=routed.graph_id,
            )
        assert snapshot.status == "executing"
        assert snapshot.accounted_cost_usd == pytest.approx(total)
        assert snapshot.actual_cost_usd == 0.0
        assert snapshot.assembly_ready is False
        assert len(snapshot.assembly_blocked_by) == 4
        assert all(scene.status == "queued" and scene.attempts == 0 for scene in snapshot.scenes)
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_multiscene_worker_crash_reclaims_only_crashed_scene_without_duplicate_submit(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("worker-crash")
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker_a = VideoExecutionAuthority(store=store, worker_id="video-project-worker-a", lease_seconds=30)
    worker_b = VideoExecutionAuthority(store=store, worker_id="video-project-worker-b", lease_seconds=30)
    try:
        routed = await create_pipeline(scope)
        rows = await execution_rows(routed.graph_id)
        total = sum(float(row.estimated_cost_usd or 0.0) for row in rows)
        async with SessionLocal() as session:
            await arm_video_project(
                session,
                organization_id=scope.org.id,
                graph_id=routed.graph_id,
                max_total_cost_usd=total,
            )
            await session.commit()

        submit = await worker_a.claim()
        assert submit is not None and submit.mode == "submit"
        await worker_a.mark_submission_started(submit)
        await worker_a.record_provider_job(
            submit,
            provider_job_id="synthetic-crash-job",
            provider_state="in_progress",
            provider_response_metadata={"synthetic": True},
            poll_after_seconds=1,
        )
        await make_available(submit.execution_id)
        stale_poll = await worker_a.claim()
        assert stale_poll is not None and stale_poll.execution_id == submit.execution_id
        assert stale_poll.mode == "poll"
        async with SessionLocal() as session:
            crashed = await session.get(VideoExecution, submit.execution_id)
            assert crashed is not None
            crashed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        resumed = await worker_b.claim()
        assert resumed is not None and resumed.execution_id == submit.execution_id
        assert resumed.mode == "poll" and resumed.provider_job_id == "synthetic-crash-job"
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, resumed.execution_id)
            assert row is not None
            estimated = float(row.estimated_cost_usd or 0.0)
            assert row.attempts == 1 and row.poll_count == 2
        await worker_b.complete_bytes(
            resumed,
            body=_MP4_ENVELOPE + b"worker-crash-resume",
            content_type="video/mp4",
            provider_response_metadata={"synthetic": True},
            usage_metadata={"seconds": 4},
            actual_cost_usd=estimated,
            cost_basis="official_fixed_second",
        )
        async with SessionLocal() as session:
            all_rows = list(
                (
                    await session.scalars(
                        select(VideoExecution)
                        .where(VideoExecution.graph_id == routed.graph_id)
                        .order_by(VideoExecution.created_at, VideoExecution.id)
                    )
                ).all()
            )
        resumed_row = next(row for row in all_rows if row.id == submit.execution_id)
        untouched = [row for row in all_rows if row.id != submit.execution_id]
        assert resumed_row.status == "completed" and resumed_row.attempts == 1
        assert all(row.status == "queued" and row.attempts == 0 for row in untouched)
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_terminal_scene_recovery_replaces_only_failed_scene_then_unblocks_final_assembly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = await seed_scope("selective-recovery")
    store = LocalMediaObjectStore(tmp_path / "objects")
    authority = VideoExecutionAuthority(store=store, worker_id="video-project-provider")
    monkeypatch.setattr(settings, "MEDIA_RENDER_TEMP_ROOT", str(tmp_path / "render"))
    media_worker = MediaRenderWorker(
        store=store,
        runtime=FakeFFmpegRuntime(),  # type: ignore[arg-type]
        worker_id="video-project-ffmpeg",
    )
    try:
        routed = await create_pipeline(scope)
        initial_rows = await execution_rows(routed.graph_id)
        total = sum(float(row.estimated_cost_usd or 0.0) for row in initial_rows)
        async with SessionLocal() as session:
            await arm_video_project(
                session,
                organization_id=scope.org.id,
                graph_id=routed.graph_id,
                max_total_cost_usd=total,
            )
            await session.commit()

        completed_ids: list[str] = []
        for _ in range(3):
            execution_id, _, _ = await complete_next_scene(authority)
            completed_ids.append(execution_id)
        failed_id, failed_scene_key, failed_estimated = await complete_next_scene(
            authority,
            terminal_failure=True,
        )

        async with SessionLocal() as session:
            failed_snapshot = await video_project_snapshot(
                session,
                organization_id=scope.org.id,
                graph_id=routed.graph_id,
            )
        assert failed_snapshot.status == "failed"
        assert failed_snapshot.assembly_ready is False
        assert len(failed_snapshot.assembly_blocked_by) == 1
        assert sum(scene.status == "completed" for scene in failed_snapshot.scenes) == 3
        assert sum(scene.status == "failed" for scene in failed_snapshot.scenes) == 1
        assert await media_worker.claim() is None

        async with SessionLocal() as session:
            replacement = await create_failed_video_scene_recovery(
                session,
                organization_id=scope.org.id,
                failed_execution_id=failed_id,
                idempotency_key="p36f-selective-recovery",
                max_attempts=1,
            )
            replacement_again = await create_failed_video_scene_recovery(
                session,
                organization_id=scope.org.id,
                failed_execution_id=failed_id,
                idempotency_key="p36f-selective-recovery",
                max_attempts=1,
            )
            assert replacement_again.id == replacement.id
            replacement_id = replacement.id
            await session.commit()

        async with SessionLocal() as session:
            before_recovery_arm = await video_project_snapshot(
                session,
                organization_id=scope.org.id,
                graph_id=routed.graph_id,
            )
        recovery_cap = before_recovery_arm.accounted_cost_usd + failed_estimated
        async with SessionLocal() as session:
            armed = await arm_video_project(
                session,
                organization_id=scope.org.id,
                graph_id=routed.graph_id,
                max_total_cost_usd=recovery_cap,
                scene_keys=(failed_scene_key,),
            )
            await session.commit()
        assert armed.armed_execution_ids == (replacement_id,)
        assert armed.projected_cost_usd == pytest.approx(recovery_cap)

        recovered_id, recovered_scene_key, _ = await complete_next_scene(authority)
        assert recovered_id == replacement_id and recovered_scene_key == failed_scene_key
        async with SessionLocal() as session:
            ready_snapshot = await video_project_snapshot(
                session,
                organization_id=scope.org.id,
                graph_id=routed.graph_id,
            )
        assert ready_snapshot.status == "assembly_ready"
        assert ready_snapshot.assembly_ready is True
        assert ready_snapshot.assembly_blocked_by == ()
        recovered_state = next(scene for scene in ready_snapshot.scenes if scene.scene_key == failed_scene_key)
        assert recovered_state.execution_id == replacement_id
        assert recovered_state.execution_count == 2
        assert recovered_state.status == "completed"

        assert await media_worker.run_once() is True
        assert await media_worker.run_once() is False
        async with SessionLocal() as session:
            final_snapshot = await video_project_snapshot(
                session,
                organization_id=scope.org.id,
                graph_id=routed.graph_id,
            )
            graph = await session.get(MediaAssetGraph, routed.graph_id)
            assembly = await session.get(MediaAssetNode, routed.assembly_node_id)
            assembly_step = await session.scalar(
                select(MediaRenderStep).where(MediaRenderStep.target_node_id == routed.assembly_node_id)
            )
            asset = await session.get(StudioAsset, scope.asset.id)
            rows = list(
                (
                    await session.scalars(
                        select(VideoExecution)
                        .where(VideoExecution.graph_id == routed.graph_id)
                        .order_by(VideoExecution.created_at, VideoExecution.id)
                    )
                ).all()
            )
        assert final_snapshot.status == "completed"
        assert graph is not None and graph.status == "completed"
        assert assembly is not None and assembly.status == "completed" and assembly.checksum
        assert assembly_step is not None and assembly_step.status == "completed"
        assert asset is not None and asset.current_revision == 2
        assert len(rows) == 5
        assert len([row for row in rows if row.target_node_id == recovered_state.target_node_id]) == 2
        assert all(
            len([candidate for candidate in rows if candidate.target_node_id == row.target_node_id]) == 1
            for row in rows
            if row.id in completed_ids
        )
        original_failed = next(row for row in rows if row.id == failed_id)
        replacement_row = next(row for row in rows if row.id == replacement_id)
        assert original_failed.status == "failed" and original_failed.provider_job_id
        assert replacement_row.status == "completed" and replacement_row.attempts == 1
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_failed_scene_recovery_refuses_unreconciled_ambiguous_submission() -> None:
    scope = await seed_scope("ambiguous-recovery")
    try:
        routed = await create_pipeline(scope)
        rows = await execution_rows(routed.graph_id)
        failed = rows[0]
        async with SessionLocal() as session:
            row = await session.get(VideoExecution, failed.id)
            assert row is not None
            row.status = "failed"
            row.provider_state = "submitting"
            row.attempts = 1
            row.provider_job_id = None
            row.error_code = "provider_submission_ambiguous"
            await session.commit()
        async with SessionLocal() as session:
            with pytest.raises(VideoProjectError, match="reconciled"):
                await create_failed_video_scene_recovery(
                    session,
                    organization_id=scope.org.id,
                    failed_execution_id=failed.id,
                    idempotency_key="p36f-ambiguous-recovery",
                )
            await session.rollback()
    finally:
        await cleanup_scope(scope)
