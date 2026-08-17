"""Phase 36D durable media render worker, fencing, and partial-revision contracts."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import (
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    Organization,
    User,
)
from app.services.media_ffmpeg import MediaRenderResult, render_command_hash
from app.services.media_graph_runtime import (
    MediaGraphScope,
    create_media_graph,
    create_partial_media_revision,
)
from app.services.media_orchestrator import MediaEdgeSpec, MediaGraphSpec, MediaNodeSpec
from app.services.media_render_worker import MediaRenderLeaseLost, MediaRenderWorker
from app.services.media_storage import LocalMediaObjectStore


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
                "format": {"duration": "1.000000", "format_name": "mov,mp4"},
            },
            engine_version="9.0",
            hardware_adapter=hardware_adapter,
        )


async def _seed_actor() -> tuple[str, str]:
    suffix = uuid4().hex[:10]
    org_id = f"p36d-org-{suffix}"
    user_id = f"p36d-user-{suffix}"
    async with SessionLocal() as session:
        session.add(Organization(id=org_id, name="Phase36D", slug=org_id, plan="enterprise", status="active"))
        await session.flush()
        session.add(
            User(
                id=user_id,
                organization_id=org_id,
                role_id=None,
                email=f"{suffix}@phase36d.example",
                name="Phase36D User",
                password_hash="unused",
                status="active",
            )
        )
        await session.commit()
    return org_id, user_id


async def _cleanup_org(org_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


def _graph_spec(*, scene_b_color: str = "#dc2626", version: int = 1) -> MediaGraphSpec:
    scene_a = MediaNodeSpec(
        key="scene-a",
        node_type="scene",
        media_type="video/mp4",
        revision=version,
        parameters={
            "operation": "render_scene",
            "output_profile": "video-mp4-h264",
            "color": "#2563eb",
            "width": 320,
            "height": 180,
            "fps": 24,
            "duration_seconds": 1.0,
            "tone_hz": 440,
        },
        provenance=({"type": "test-source", "scene": "a"},),
    )
    scene_b = MediaNodeSpec(
        key="scene-b",
        node_type="scene",
        media_type="video/mp4",
        revision=version,
        parameters={
            "operation": "render_scene",
            "output_profile": "video-mp4-h264",
            "color": scene_b_color,
            "width": 320,
            "height": 180,
            "fps": 24,
            "duration_seconds": 1.0,
            "tone_hz": 660,
        },
        provenance=({"type": "test-source", "scene": "b"},),
    )
    final = MediaNodeSpec(
        key="final",
        node_type="assembly",
        media_type="video/mp4",
        revision=version,
        parameters={"operation": "assemble", "output_profile": "video-mp4-h264"},
    )
    return MediaGraphSpec(
        title="Phase36D two-scene acceptance",
        asset_kind="video",
        nodes=(scene_a, scene_b, final),
        edges=(
            MediaEdgeSpec("scene-a", "final", ordinal=0),
            MediaEdgeSpec("scene-b", "final", ordinal=1),
        ),
        output_profile="video-mp4-h264",
        graph_version=version,
        rights_metadata={"consent": "synthetic-test"},
        provenance=({"type": "phase36d-test"},),
    )


async def _drain(worker: MediaRenderWorker, limit: int = 20) -> int:
    count = 0
    for _ in range(limit):
        if not await worker.run_once():
            break
        count += 1
    return count


@pytest.mark.asyncio
async def test_media_worker_completes_dag_and_partial_revision_reuses_unaffected_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, user_id = await _seed_actor()
    monkeypatch.setattr(settings, "MEDIA_RENDER_TEMP_ROOT", str(tmp_path / "render"))
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker = MediaRenderWorker(
        store=store,
        runtime=FakeFFmpegRuntime(),  # type: ignore[arg-type]
        worker_id="phase36d-worker-a",
    )
    try:
        async with SessionLocal() as session:
            first = await create_media_graph(
                session,
                scope=MediaGraphScope(organization_id=org_id, created_by_id=user_id),
                spec=_graph_spec(),
                idempotency_key="phase36d-first",
            )
            first_again = await create_media_graph(
                session,
                scope=MediaGraphScope(organization_id=org_id, created_by_id=user_id),
                spec=_graph_spec(),
                idempotency_key="phase36d-first",
            )
            assert first_again.id == first.id
            first_id = first.id
            await session.commit()

        assert await _drain(worker) == 3
        async with SessionLocal() as session:
            first = await session.get(MediaAssetGraph, first_id)
            assert first is not None and first.status == "completed"
            first_nodes = {
                row.logical_key: row
                for row in (
                    await session.scalars(select(MediaAssetNode).where(MediaAssetNode.graph_id == first_id))
                ).all()
            }
            assert all(row.status == "completed" and row.checksum for row in first_nodes.values())
            scene_a_checksum = str(first_nodes["scene-a"].checksum)
            final_checksum_v1 = str(first_nodes["final"].checksum)
            revised, affected = await create_partial_media_revision(
                session,
                graph=first,
                created_by_id=user_id,
                node_parameter_updates={"scene-b": {"color": "#16a34a"}},
                idempotency_key="phase36d-revision-2",
            )
            revised_id = revised.id
            assert affected == ("scene-b", "final")
            await session.commit()

        async with SessionLocal() as session:
            revised_nodes = {
                row.logical_key: row
                for row in (
                    await session.scalars(select(MediaAssetNode).where(MediaAssetNode.graph_id == revised_id))
                ).all()
            }
            assert revised_nodes["scene-a"].status == "completed"
            assert revised_nodes["scene-a"].checksum == scene_a_checksum
            steps = list(
                (
                    await session.scalars(
                        select(MediaRenderStep).where(MediaRenderStep.graph_id == revised_id)
                    )
                ).all()
            )
            step_targets = {
                (await session.get(MediaAssetNode, step.target_node_id)).logical_key  # type: ignore[union-attr]
                for step in steps
            }
            assert step_targets == {"scene-b", "final"}

        assert await _drain(worker) == 2
        async with SessionLocal() as session:
            revised = await session.get(MediaAssetGraph, revised_id)
            assert revised is not None and revised.status == "completed"
            final = await session.scalar(
                select(MediaAssetNode).where(
                    MediaAssetNode.graph_id == revised_id,
                    MediaAssetNode.logical_key == "final",
                )
            )
            scene_a = await session.scalar(
                select(MediaAssetNode).where(
                    MediaAssetNode.graph_id == revised_id,
                    MediaAssetNode.logical_key == "scene-a",
                )
            )
            assert final is not None and final.checksum != final_checksum_v1
            assert scene_a is not None and scene_a.checksum == scene_a_checksum
            assert any(item.get("type") == "reused-render" for item in scene_a.provenance)
    finally:
        await _cleanup_org(org_id)


@pytest.mark.asyncio
async def test_media_worker_reclaims_expired_lease_and_rejects_stale_fencing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, user_id = await _seed_actor()
    monkeypatch.setattr(settings, "MEDIA_RENDER_TEMP_ROOT", str(tmp_path / "render"))
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker_a = MediaRenderWorker(store=store, runtime=FakeFFmpegRuntime(), worker_id="worker-a")  # type: ignore[arg-type]
    worker_b = MediaRenderWorker(store=store, runtime=FakeFFmpegRuntime(), worker_id="worker-b")  # type: ignore[arg-type]
    single = MediaGraphSpec(
        title="fencing",
        asset_kind="video",
        nodes=(
            MediaNodeSpec(
                key="scene",
                node_type="scene",
                media_type="video/mp4",
                parameters={"operation": "render_scene", "output_profile": "video-mp4-h264"},
            ),
        ),
        edges=(),
        output_profile="video-mp4-h264",
    )
    try:
        async with SessionLocal() as session:
            graph = await create_media_graph(
                session,
                scope=MediaGraphScope(organization_id=org_id, created_by_id=user_id),
                spec=single,
                idempotency_key="fencing-graph",
            )
            await session.commit()
        claim_a = await worker_a.claim()
        assert claim_a is not None and claim_a.fencing_token == 1
        async with SessionLocal() as session:
            step = await session.get(MediaRenderStep, claim_a.step_id)
            assert step is not None
            step.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        claim_b = await worker_b.claim()
        assert claim_b is not None
        assert claim_b.step_id == claim_a.step_id
        assert claim_b.fencing_token == 2
        with pytest.raises(MediaRenderLeaseLost):
            await worker_a.renew(claim_a)
        await worker_b.execute(claim_b)
        async with SessionLocal() as session:
            step = await session.get(MediaRenderStep, claim_b.step_id)
            assert step is not None and step.status == "completed"
            assert step.fencing_token == 2
            assert int(
                await session.scalar(
                    select(func.count(MediaRenderStep.id)).where(
                        MediaRenderStep.graph_id == graph.id,
                        MediaRenderStep.status == "completed",
                    )
                )
                or 0
            ) == 1
    finally:
        await _cleanup_org(org_id)


def test_phase36d_render_schema_includes_expiry_fencing_and_retry_fields() -> None:
    from app.db.base import Base
    import app.db.models  # noqa: F401

    columns = set(Base.metadata.tables["media_render_steps"].c.keys())
    assert {
        "lease_token",
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "available_at",
        "attempts",
        "max_attempts",
        "idempotency_key",
    } <= columns
