from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import (
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    Organization,
    Project,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    User,
    Workspace,
)
from app.services.media_ffmpeg import MediaRenderResult
from app.services.media_graph_runtime import (
    MediaGraphScope,
    create_media_graph,
    create_partial_media_revision,
)
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec
from app.services.media_render_worker import (
    MediaRenderLeaseLost,
    MediaRenderWorker,
)
from app.services.media_storage import LocalMediaObjectStore


class DeterministicRuntime:
    def preflight(self) -> dict[str, object]:
        return {
            "engine": "ffmpeg",
            "version": "9.0",
            "required_encoders": ["libx264", "aac"],
            "hardware_adapters": ["software"],
        }

    def render(
        self,
        *,
        operation: str,
        profile_id: str,
        input_paths: list[Path],
        output_path: Path,
        metadata: dict[str, object],
        input_checksums: list[str],
        hardware_adapter: str = "software",
    ) -> MediaRenderResult:
        payload = json.dumps(
            {
                "operation": operation,
                "profile": profile_id,
                "metadata": metadata,
                "inputs": input_checksums,
                "adapter": hardware_adapter,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        body = b"phase36d-render:" + hashlib.sha256(payload).hexdigest().encode()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(body)
        return MediaRenderResult(
            output_path=output_path,
            command_hash=hashlib.sha256(payload).hexdigest(),
            probe={
                "format": {"duration": "1.000", "format_name": "mov,mp4"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 320,
                        "height": 180,
                        "pix_fmt": "yuv420p",
                    }
                ],
            },
            engine_version="9.0",
            hardware_adapter=hardware_adapter,
        )


async def _seed_scope(tag: str) -> MediaGraphScope:
    suffix = f"{tag}-{uuid4().hex[:8]}"
    org = Organization(
        id=f"p36d-org-{uuid4().hex[:20]}",
        name=f"Phase 36D {suffix}",
        slug=f"p36d-{suffix}",
        plan="enterprise",
        status="active",
    )
    user = User(
        id=f"p36d-user-{uuid4().hex[:18]}",
        organization_id=org.id,
        role_id=None,
        email=f"{suffix}@example.com",
        name="Phase 36D Operator",
        password_hash="unused",
        status="active",
    )
    workspace = Workspace(
        id=f"p36d-ws-{uuid4().hex[:21]}",
        organization_id=org.id,
        name="Phase 36D Workspace",
        slug=f"p36d-ws-{suffix}",
        status="active",
    )
    project = Project(
        id=f"p36d-project-{uuid4().hex[:16]}",
        organization_id=org.id,
        workspace_id=workspace.id,
        owner_id=user.id,
        name="Phase 36D Media Project",
        slug=f"p36d-project-{suffix}",
        description="Real media graph acceptance.",
        status="active",
        priority="high",
        progress=10,
    )
    async with SessionLocal() as session:
        session.add(org)
        await session.flush()
        session.add_all([user, workspace])
        await session.flush()
        session.add(project)
        await session.commit()
    return MediaGraphScope(
        organization_id=org.id,
        created_by_id=user.id,
        workspace_id=workspace.id,
        project_id=project.id,
    )


async def _cleanup_scope(scope: MediaGraphScope) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(MediaAssetGraph).where(
                MediaAssetGraph.organization_id == scope.organization_id
            )
        )
        if scope.project_id:
            await session.execute(delete(Project).where(Project.id == scope.project_id))
        if scope.workspace_id:
            await session.execute(delete(Workspace).where(Workspace.id == scope.workspace_id))
        await session.execute(delete(User).where(User.id == scope.created_by_id))
        await session.execute(
            delete(Organization).where(Organization.id == scope.organization_id)
        )
        await session.commit()


def _spec(*, scene_a_color: str = "#1d4ed8", version: int = 1) -> MediaGraphSpec:
    return MediaGraphSpec(
        title="Phase 36D scene revision",
        asset_kind="video",
        graph_version=version,
        output_profile="video-mp4-h264",
        rights_metadata={"owner_consent": True},
        provenance=({"source": "phase36d-acceptance", "type": "test"},),
        nodes=(
            MediaNodeSpec(
                key="scene-a",
                node_type="scene",
                media_type="video/mp4",
                parameters={
                    "operation": "render_scene",
                    "output_profile": "video-mp4-h264",
                    "color": scene_a_color,
                    "duration_seconds": 1.0,
                    "width": 320,
                    "height": 180,
                    "fps": 24,
                },
                scene_metadata={"index": 1},
            ),
            MediaNodeSpec(
                key="scene-b",
                node_type="scene",
                media_type="video/mp4",
                parameters={
                    "operation": "render_scene",
                    "output_profile": "video-mp4-h264",
                    "color": "#0f766e",
                    "duration_seconds": 1.0,
                    "width": 320,
                    "height": 180,
                    "fps": 24,
                },
                scene_metadata={"index": 2},
            ),
            MediaNodeSpec(
                key="assembly",
                node_type="assembly",
                media_type="video/mp4",
                parameters={
                    "operation": "assemble",
                    "output_profile": "video-mp4-h264",
                },
            ),
        ),
        edges=(
            MediaEdgeSpec("scene-a", "assembly", ordinal=0),
            MediaEdgeSpec("scene-b", "assembly", ordinal=1),
        ),
    )


async def _drain(worker: MediaRenderWorker, *, limit: int = 10) -> int:
    processed = 0
    for _ in range(limit):
        claim = await worker.claim()
        if claim is None:
            break
        await worker.execute(claim)
        processed += 1
    return processed


@pytest.mark.asyncio
async def test_media_graph_executes_in_dependency_order_and_partial_revision_reuses_unaffected_scene(
    tmp_path: Path,
) -> None:
    scope = await _seed_scope("partial")
    try:
        async with SessionLocal() as session:
            graph = await create_media_graph(
                session,
                scope=scope,
                spec=_spec(),
                idempotency_key=f"initial-{uuid4()}",
            )
            graph_id = graph.id
            await session.commit()

        worker = MediaRenderWorker(
            worker_id="phase36d-worker-a",
            store=LocalMediaObjectStore(tmp_path / "media"),
            runtime=DeterministicRuntime(),  # type: ignore[arg-type]
        )
        assert await _drain(worker) == 3

        async with SessionLocal() as session:
            graph = await session.get(MediaAssetGraph, graph_id)
            assert graph is not None and graph.status == "completed"
            nodes = {
                item.logical_key: item
                for item in (
                    await session.scalars(
                        select(MediaAssetNode).where(MediaAssetNode.graph_id == graph_id)
                    )
                ).all()
            }
            assert set(nodes) == {"scene-a", "scene-b", "assembly"}
            assert all(item.status == "completed" for item in nodes.values())
            assert all(item.checksum and item.storage_key for item in nodes.values())
            scene_b_checksum = nodes["scene-b"].checksum
            scene_b_storage = nodes["scene-b"].storage_key
            initial_scene_a_checksum = nodes["scene-a"].checksum
            revised, affected = await create_partial_media_revision(
                session,
                graph=graph,
                created_by_id=scope.created_by_id,
                node_parameter_updates={"scene-a": {"color": "#991b1b"}},
                idempotency_key=f"revision-{uuid4()}",
            )
            revised_id = revised.id
            assert affected == ("scene-a", "assembly")
            await session.commit()

        async with SessionLocal() as session:
            revised_nodes = {
                item.logical_key: item
                for item in (
                    await session.scalars(
                        select(MediaAssetNode).where(MediaAssetNode.graph_id == revised_id)
                    )
                ).all()
            }
            assert revised_nodes["scene-b"].status == "completed"
            assert revised_nodes["scene-b"].checksum == scene_b_checksum
            assert revised_nodes["scene-b"].storage_key == scene_b_storage
            assert any(
                entry.get("type") == "reused-render"
                for entry in revised_nodes["scene-b"].provenance
            )
            step_keys = set(
                (
                    await session.scalars(
                        select(MediaRenderStep.step_key).where(
                            MediaRenderStep.graph_id == revised_id
                        )
                    )
                ).all()
            )
            assert len(step_keys) == 2
            assert any(key.startswith("scene-a:") for key in step_keys)
            assert any(key.startswith("assembly:") for key in step_keys)
            assert not any(key.startswith("scene-b:") for key in step_keys)

        assert await _drain(worker) == 2
        async with SessionLocal() as session:
            revised = await session.get(MediaAssetGraph, revised_id)
            assert revised is not None and revised.status == "completed"
            revised_scene_a = await session.scalar(
                select(MediaAssetNode).where(
                    MediaAssetNode.graph_id == revised_id,
                    MediaAssetNode.logical_key == "scene-a",
                )
            )
            assert revised_scene_a is not None
            assert revised_scene_a.checksum != initial_scene_a_checksum
            assert any(
                entry.get("type") == "ffmpeg-render"
                for entry in revised_scene_a.provenance
            )
    finally:
        await _cleanup_scope(scope)


@pytest.mark.asyncio
async def test_reclaimed_render_lease_rejects_stale_completion(tmp_path: Path) -> None:
    scope = await _seed_scope("fence")
    try:
        single = MediaGraphSpec(
            title="Fencing",
            asset_kind="video",
            output_profile="video-mp4-h264",
            nodes=(
                MediaNodeSpec(
                    "scene",
                    "scene",
                    media_type="video/mp4",
                    parameters={
                        "operation": "render_scene",
                        "output_profile": "video-mp4-h264",
                    },
                ),
            ),
            edges=(),
        )
        async with SessionLocal() as session:
            graph = await create_media_graph(
                session,
                scope=scope,
                spec=single,
                idempotency_key=f"fence-{uuid4()}",
            )
            graph_id = graph.id
            await session.commit()

        store = LocalMediaObjectStore(tmp_path / "media-fence")
        runtime = DeterministicRuntime()
        worker_a = MediaRenderWorker(
            worker_id="phase36d-worker-a", store=store, runtime=runtime  # type: ignore[arg-type]
        )
        worker_b = MediaRenderWorker(
            worker_id="phase36d-worker-b", store=store, runtime=runtime  # type: ignore[arg-type]
        )
        claim_a = await worker_a.claim()
        assert claim_a is not None
        async with SessionLocal() as session:
            step = await session.get(MediaRenderStep, claim_a.step_id)
            assert step is not None
            step.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
            await session.commit()
        claim_b = await worker_b.claim()
        assert claim_b is not None
        assert claim_b.step_id == claim_a.step_id
        assert claim_b.fencing_token > claim_a.fencing_token

        result = MediaRenderResult(
            output_path=tmp_path / "stale.mp4",
            command_hash="a" * 64,
            probe={"format": {}, "streams": [{"codec_type": "video"}]},
            engine_version="9.0",
            hardware_adapter="software",
        )
        with pytest.raises(MediaRenderLeaseLost):
            await worker_a._complete(
                claim_a,
                stored_key="media/stale.mp4",
                stored_backend="local",
                stored_size=10,
                stored_checksum="b" * 64,
                render=result,
                input_checksums=[],
            )
        async with SessionLocal() as session:
            current = await session.get(MediaRenderStep, claim_b.step_id)
            assert current is not None
            assert current.status == "running"
            assert current.lease_owner == "phase36d-worker-b"
            assert current.fencing_token == claim_b.fencing_token
            graph = await session.get(MediaAssetGraph, graph_id)
            assert graph is not None and graph.status == "planned"
    finally:
        await _cleanup_scope(scope)


def test_universal_builder_storyboard_converts_to_executable_media_dag() -> None:
    import json
    from aios.universal_project_builder import _media_target
    from app.services.media_orchestrator import media_graph_from_universal_storyboard

    package = _media_target("phase36d-universal", {"title": "Universal Builder Media"})
    storyboard = json.loads(package["targets/media/storyboard.json"])
    graph = media_graph_from_universal_storyboard(storyboard)
    assert graph.asset_kind == "video"
    assert graph.output_profile == "video-mp4-h264"
    assert graph.topological_order[-1] == "assembly"
    scene_nodes = [node for node in graph.nodes if node.node_type == "scene"]
    assert len(scene_nodes) == 3
    assert all(node.parameters["operation"] == "render_scene" for node in scene_nodes)
    assert all(node.parameters["hardware_adapter"] == "software" for node in scene_nodes)
    assert all(node.timeline_metadata["duration_seconds"] > 0 for node in scene_nodes)
    assembly = next(node for node in graph.nodes if node.key == "assembly")
    assert assembly.parameters["operation"] == "assemble"
    assert len(graph.edges) == 3
    assert graph.provenance[0]["type"] == "universal-builder-media-target"


@pytest.mark.asyncio
async def test_completed_graph_materializes_a_real_studio_asset_revision(tmp_path: Path) -> None:
    scope = await _seed_scope("studio-revision")
    job_id = f"p36d-job-{uuid4().hex[:20]}"
    asset_id = f"p36d-asset-{uuid4().hex[:18]}"
    try:
        async with SessionLocal() as session:
            job = StudioJob(
                id=job_id,
                organization_id=scope.organization_id,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                requested_by_id=scope.created_by_id,
                department="video",
                output_kind="video",
                title="Phase 36D Studio Render",
                brief="Render a real governed media revision.",
                language="en-US",
                style="modern",
                provider_mode="provider_neutral",
                status="completed",
                progress=100,
                safety_status="passed",
                request_metadata={},
                result_metadata={},
                max_attempts=3,
            )
            session.add(job)
            await session.flush()
            asset = StudioAsset(
                id=asset_id,
                organization_id=scope.organization_id,
                job_id=job.id,
                project_id=scope.project_id,
                created_by_id=scope.created_by_id,
                department="video",
                asset_type="video",
                title=job.title,
                filename="phase36d-source.zip",
                media_type="application/zip",
                storage_path="/tmp/phase36d-source.zip",
                checksum="1" * 64,
                size_bytes=1,
                status="active",
                current_revision=1,
                asset_metadata={"manifest": {"provider_mode": "provider_neutral"}},
            )
            session.add(asset)
            session.add(
                StudioAssetRevision(
                    id=f"p36d-rev-{uuid4().hex[:20]}",
                    organization_id=scope.organization_id,
                    asset_id=asset.id,
                    job_id=job.id,
                    created_by_id=scope.created_by_id,
                    revision_number=1,
                    filename=asset.filename,
                    media_type=asset.media_type,
                    storage_path=asset.storage_path,
                    checksum=asset.checksum,
                    size_bytes=asset.size_bytes,
                    revision_metadata={"manifest": {"provider_mode": "provider_neutral"}},
                    status="active",
                )
            )
            await session.commit()

        single = MediaGraphSpec(
            title="Phase 36D Studio Render",
            asset_kind="video",
            output_profile="video-mp4-h264",
            nodes=(
                MediaNodeSpec(
                    "final",
                    "scene",
                    media_type="video/mp4",
                    parameters={
                        "operation": "render_scene",
                        "output_profile": "video-mp4-h264",
                        "color": "#1d4ed8",
                        "duration_seconds": 1.0,
                        "width": 320,
                        "height": 180,
                        "fps": 24,
                    },
                ),
            ),
            edges=(),
            rights_metadata={"owner_consent": True},
        )
        async with SessionLocal() as session:
            graph = await create_media_graph(
                session,
                scope=MediaGraphScope(
                    organization_id=scope.organization_id,
                    created_by_id=scope.created_by_id,
                    workspace_id=scope.workspace_id,
                    project_id=scope.project_id,
                    studio_job_id=job_id,
                    studio_asset_id=asset_id,
                ),
                spec=single,
                idempotency_key=f"studio-output-{uuid4()}",
            )
            graph_id = graph.id
            await session.commit()

        worker = MediaRenderWorker(
            worker_id="phase36d-studio-worker",
            store=LocalMediaObjectStore(tmp_path / "studio-media"),
            runtime=DeterministicRuntime(),  # type: ignore[arg-type]
        )
        assert await _drain(worker) == 1
        async with SessionLocal() as session:
            asset = await session.get(StudioAsset, asset_id)
            assert asset is not None and asset.current_revision == 2
            assert asset.media_type == "video/mp4"
            output = (asset.asset_metadata or {}).get("media_graph_output")
            assert isinstance(output, dict)
            assert output["graph_id"] == graph_id
            assert output["engine_version"] == "9.0"
            revision = await session.scalar(
                select(StudioAssetRevision).where(
                    StudioAssetRevision.asset_id == asset_id,
                    StudioAssetRevision.revision_number == 2,
                )
            )
            assert revision is not None
            revision_output = (revision.revision_metadata or {}).get("media_graph_output")
            assert isinstance(revision_output, dict)
            assert revision_output["graph_id"] == graph_id
            assert revision.checksum == asset.checksum
            graph = await session.get(MediaAssetGraph, graph_id)
            assert graph is not None
            assert graph.graph_metadata["studio_revision_number"] == 2
    finally:
        async with SessionLocal() as session:
            await session.execute(
                delete(MediaAssetGraph).where(
                    MediaAssetGraph.organization_id == scope.organization_id
                )
            )
            await session.execute(
                delete(StudioAssetRevision).where(
                    StudioAssetRevision.organization_id == scope.organization_id
                )
            )
            await session.execute(
                delete(StudioAsset).where(
                    StudioAsset.organization_id == scope.organization_id
                )
            )
            await session.execute(
                delete(StudioJob).where(StudioJob.organization_id == scope.organization_id)
            )
            await session.commit()
        await _cleanup_scope(scope)
