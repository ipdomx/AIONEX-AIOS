"""Phase 36G provider-neutral local audio Media DAG contracts."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from aios.audio_factory import AudioRequest, build_audio_plan
from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import (
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    Organization,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    User,
)
from app.services.audio_pipeline import (
    AudioPipelineError,
    LocalAudioSourceBinding,
    build_local_audio_graph_spec,
    create_local_audio_pipeline,
)
from app.services.media_ffmpeg import MediaRenderResult, render_command_hash
from app.services.media_graph_runtime import (
    MediaGraphScope,
    create_media_graph,
    create_partial_media_revision,
)
from app.services.media_orchestrator import MediaGraphSpec, MediaNodeSpec
from app.services.media_render_worker import MediaRenderLeaseLost, MediaRenderWorker
from app.services.media_storage import LocalMediaObjectStore
from sqlalchemy import delete, func, select


class FakeAudioRuntime:
    def preflight(self) -> dict[str, object]:
        return {
            "engine": "ffmpeg",
            "version": "9.0",
            "required_audio_filters": [
                "adelay",
                "amix",
                "aresample",
                "astats",
                "ebur128",
                "highpass",
                "loudnorm",
                "lowpass",
                "showwavespic",
                "silencedetect",
            ],
            "hardware_adapters": ["software"],
        }

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
        payload = json.dumps(
            {
                "operation": operation,
                "profile": profile_id,
                "metadata": metadata,
                "checksums": input_checksums,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        body = payload + b"\n" + b"".join(path.read_bytes() for path in input_paths)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(hashlib.sha256(body).digest() * 32)
        if profile_id == "image-png-lossless":
            streams = [
                {
                    "codec_type": "video",
                    "codec_name": "png",
                    "width": int(metadata.get("width", 1_200)),
                    "height": int(metadata.get("height", 320)),
                }
            ]
            format_data = {"format_name": "png_pipe"}
        else:
            codec = {
                "audio-wav-pcm": "pcm_s16le",
                "audio-wav-pcm-mono": "pcm_s16le",
                "audio-m4a-aac": "aac",
                "audio-webm-opus": "opus",
            }[profile_id]
            channels = 1 if profile_id == "audio-wav-pcm-mono" else 2
            streams = [
                {
                    "codec_type": "audio",
                    "codec_name": codec,
                    "sample_rate": "48000",
                    "channels": channels,
                }
            ]
            format_data = {
                "format_name": {
                    "audio-wav-pcm": "wav",
                    "audio-wav-pcm-mono": "wav",
                    "audio-m4a-aac": "mov,mp4,m4a,3gp,3g2,mj2",
                    "audio-webm-opus": "matroska,webm",
                }[profile_id],
                "duration": "2.000",
            }
        qa: dict[str, object] = {
            "passed": True,
            "profile": profile_id,
            "operation": operation,
        }
        if operation in {"audio_master", "audio_export"}:
            qa["audio_analysis"] = {
                "schema": "36G.audio-qa.v1",
                "integrated_lufs": -16.0,
                "true_peak_dbtp": -2.0,
                "loudness_range_lu": 1.0,
                "silence_segment_count": 0,
                "silence_duration_seconds": 0.0,
                "clipped": False,
                "passed": True,
            }
        return MediaRenderResult(
            output_path=output_path,
            command_hash=render_command_hash(
                operation=operation,
                profile_id=profile_id,
                metadata=metadata,
                input_checksums=input_checksums,
            ),
            probe={"streams": streams, "format": format_data},
            engine_version="9.0",
            hardware_adapter=hardware_adapter,
            qa=qa,
        )


async def _seed_actor_and_studio() -> tuple[str, str, str, str]:
    suffix = uuid4().hex[:12]
    org_id = f"p36g-org-{suffix}"
    user_id = f"p36g-user-{suffix}"
    job_id = f"p36g-job-{suffix}"
    asset_id = f"p36g-asset-{suffix}"
    async with SessionLocal() as session:
        org = Organization(
            id=org_id,
            name="Phase 36G Audio Runtime",
            slug=org_id,
            plan="enterprise",
            status="active",
        )
        user = User(
            id=user_id,
            organization_id=org_id,
            role_id=None,
            email=f"{suffix}@phase36g.example.invalid",
            name="Phase36G User",
            password_hash="unused",
            status="active",
        )
        session.add(org)
        await session.flush()
        session.add(user)
        await session.flush()
        job = StudioJob(
            id=job_id,
            organization_id=org_id,
            workspace_id=None,
            project_id=None,
            requested_by_id=user_id,
            department="audio",
            output_kind="audio",
            title="Phase 36G local audio runtime",
            brief="Clean, align, mix and master governed local audio sources.",
            language="en-US",
            style="documentary",
            provider_mode="provider_neutral",
            status="completed",
            progress=100,
            safety_status="passed",
            request_metadata={},
            result_metadata={},
            max_attempts=1,
        )
        session.add(job)
        await session.flush()
        asset = StudioAsset(
            id=asset_id,
            organization_id=org_id,
            job_id=job_id,
            project_id=None,
            created_by_id=user_id,
            department="audio",
            asset_type="audio",
            title=job.title,
            filename="phase36g-source.zip",
            media_type="application/zip",
            storage_path="/tmp/phase36g-source.zip",
            checksum="1" * 64,
            size_bytes=1,
            status="active",
            current_revision=1,
            asset_metadata={
                "manifest": {
                    "provider_mode": "provider_neutral",
                    "external_requests": 0,
                    "external_cost_usd": 0,
                }
            },
        )
        session.add(asset)
        session.add(
            StudioAssetRevision(
                id=f"p36g-rev-{suffix}",
                organization_id=org_id,
                asset_id=asset_id,
                job_id=job_id,
                created_by_id=user_id,
                revision_number=1,
                filename=asset.filename,
                media_type=asset.media_type,
                storage_path=asset.storage_path,
                checksum=asset.checksum,
                size_bytes=asset.size_bytes,
                revision_metadata=asset.asset_metadata,
                status="active",
            )
        )
        await session.commit()
    return org_id, user_id, job_id, asset_id


async def _seed_sources(
    *,
    org_id: str,
    user_id: str,
    store: LocalMediaObjectStore,
    count: int = 2,
) -> tuple[MediaAssetNode, ...]:
    nodes = tuple(
        MediaNodeSpec(
            key=f"input-{index:03d}",
            node_type="audio-source",
            media_type="audio/wav",
            provenance=({"type": "phase36g-test-source", "index": index},),
        )
        for index in range(1, count + 1)
    )
    spec = MediaGraphSpec(
        title="Phase 36G governed audio sources",
        asset_kind="audio",
        nodes=nodes,
        edges=(),
        output_profile="audio-wav-pcm",
        provenance=({"type": "phase36g-local-source-fixture"},),
    )
    async with SessionLocal() as session:
        graph = await create_media_graph(
            session,
            scope=MediaGraphScope(organization_id=org_id, created_by_id=user_id),
            spec=spec,
            idempotency_key=f"phase36g-sources-{uuid4()}",
        )
        rows = list(
            (
                await session.scalars(
                    select(MediaAssetNode)
                    .where(MediaAssetNode.graph_id == graph.id)
                    .order_by(MediaAssetNode.logical_key)
                )
            ).all()
        )
        for index, row in enumerate(rows, start=1):
            body = (f"phase36g-audio-source-{index}".encode()) * 128
            stored = store.put_bytes(
                f"sources/{org_id}/{row.id}.wav", body, "audio/wav"
            )
            row.status = "completed"
            row.storage_backend = stored.backend
            row.storage_key = stored.key
            row.checksum = stored.sha256
            row.size_bytes = stored.size_bytes
        graph.status = "completed"
        await session.commit()
        for row in rows:
            session.expunge(row)
        return tuple(rows)


async def _cleanup_org(org_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


def _plan(*, source_count: int = 2, profile: str = "wav-pcm-48k-stereo"):
    return build_audio_plan(
        AudioRequest(
            title="Phase 36G local audio runtime",
            brief="Clean, align, mix and master tenant-scoped governed audio.",
            operation="cleanup-master",
            use_case="general",
            language="en-US",
            purpose="production audio cleanup",
            source_count=source_count,
            voice_mode="none",
            output_profile_id=profile,
        )
    )


async def _drain(worker: MediaRenderWorker, limit: int = 30) -> int:
    processed = 0
    for _ in range(limit):
        if not await worker.run_once():
            break
        processed += 1
    return processed


def test_local_audio_graph_is_deterministic_and_keeps_provider_tasks_out() -> None:
    plan = _plan()
    rows = []
    for index in range(2):
        node = MediaAssetNode(
            id=f"source-{index}",
            graph_id="source-graph",
            organization_id="org",
            created_by_id="user",
            logical_key=f"input-{index}",
            revision=1,
            node_type="audio-source",
            media_type="audio/wav",
            status="completed",
            storage_backend="local",
            storage_key=f"source-{index}.wav",
            checksum=hashlib.sha256(f"source-{index}".encode()).hexdigest(),
            size_bytes=100,
            idempotency_key=f"source-{index}",
            source_metadata={},
            prompt_metadata={},
            rights_metadata={},
            provenance=[],
            scene_metadata={},
            timeline_metadata={},
            operation_metadata={},
        )
        rows.append(LocalAudioSourceBinding(node, offset_ms=index * 250, gain_db=-index))
    first = build_local_audio_graph_spec(plan, sources=tuple(rows))
    second = build_local_audio_graph_spec(plan, sources=tuple(rows))
    assert first.checksum == second.checksum
    assert first.asset_kind == "mixed"
    assert first.output_profile == "audio-wav-pcm"
    assert first.topological_order[-1] == "export"
    operations = {
        str(node.parameters.get("operation"))
        for node in first.nodes
        if node.parameters.get("operation")
    }
    assert operations == {
        "audio_cleanup",
        "audio_align",
        "audio_mix",
        "audio_master",
        "audio_waveform",
        "audio_export",
    }
    assert not operations & {
        "transcribe",
        "synthesize-speech",
        "compose-music",
        "voice-transform",
        "voice-clone",
    }
    export_parents = [edge for edge in first.edges if edge.child == "export"]
    assert [(edge.parent, edge.ordinal) for edge in export_parents] == [
        ("master", 0),
        ("waveform", 1),
    ]


def test_local_audio_graph_rejects_provider_operation_and_source_mismatch() -> None:
    narration = build_audio_plan(
        AudioRequest(
            title="Narration",
            brief="Narrate this governed source without fabricating a live provider result.",
            operation="narration",
            use_case="general",
            language="en-US",
            purpose="test",
            source_count=0,
            voice_mode="stock",
        )
    )
    with pytest.raises(AudioPipelineError, match="cleanup-master"):
        build_local_audio_graph_spec(narration, sources=())
    source = MediaAssetNode(
        id="mismatch-source",
        graph_id="source-graph",
        organization_id="org",
        created_by_id="user",
        logical_key="source",
        revision=1,
        node_type="audio-source",
        media_type="audio/wav",
        status="completed",
        storage_backend="local",
        storage_key="source.wav",
        checksum="b" * 64,
        size_bytes=1,
        idempotency_key="mismatch-source",
        source_metadata={},
        prompt_metadata={},
        rights_metadata={},
        provenance=[],
        scene_metadata={},
        timeline_metadata={},
        operation_metadata={},
    )
    with pytest.raises(AudioPipelineError, match="source count"):
        build_local_audio_graph_spec(
            _plan(source_count=2),
            sources=(LocalAudioSourceBinding(source),),
        )


@pytest.mark.parametrize(
    ("factory_profile", "media_profile"),
    [
        ("wav-pcm-48k-stereo", "audio-wav-pcm"),
        ("wav-pcm-48k-mono", "audio-wav-pcm-mono"),
        ("m4a-aac-48k-stereo", "audio-m4a-aac"),
        ("webm-opus-48k-stereo", "audio-webm-opus"),
    ],
)
def test_local_audio_profile_mapping_is_exact(
    factory_profile: str, media_profile: str
) -> None:
    node = MediaAssetNode(
        id="source",
        graph_id="source-graph",
        organization_id="org",
        created_by_id="user",
        logical_key="source",
        revision=1,
        node_type="audio-source",
        media_type="audio/wav",
        status="completed",
        storage_backend="local",
        storage_key="source.wav",
        checksum="a" * 64,
        size_bytes=1,
        idempotency_key="source",
        source_metadata={},
        prompt_metadata={},
        rights_metadata={},
        provenance=[],
        scene_metadata={},
        timeline_metadata={},
        operation_metadata={},
    )
    spec = build_local_audio_graph_spec(
        _plan(source_count=1, profile=factory_profile),
        sources=(LocalAudioSourceBinding(node),),
    )
    assert spec.output_profile == media_profile
    export = next(item for item in spec.nodes if item.key == "export")
    assert export.parameters["output_profile"] == media_profile


@pytest.mark.asyncio
async def test_audio_pipeline_completes_studio_revision_and_partial_revision_reuses_unaffected_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, user_id, job_id, asset_id = await _seed_actor_and_studio()
    store = LocalMediaObjectStore(tmp_path / "objects")
    monkeypatch.setattr(settings, "MEDIA_RENDER_TEMP_ROOT", str(tmp_path / "render"))
    sources = await _seed_sources(org_id=org_id, user_id=user_id, store=store)
    worker = MediaRenderWorker(
        store=store,
        runtime=FakeAudioRuntime(),  # type: ignore[arg-type]
        worker_id="phase36g-audio-worker",
    )
    try:
        async with SessionLocal() as session:
            result = await create_local_audio_pipeline(
                session,
                scope=MediaGraphScope(
                    organization_id=org_id,
                    created_by_id=user_id,
                    studio_job_id=job_id,
                    studio_asset_id=asset_id,
                ),
                plan=_plan(),
                sources=(
                    LocalAudioSourceBinding(sources[0], offset_ms=0, gain_db=0.0),
                    LocalAudioSourceBinding(sources[1], offset_ms=250, gain_db=-3.0),
                ),
                idempotency_key="phase36g-audio-first",
            )
            first_id = result.graph_id
            assert result.external_requests == 0
            assert result.external_cost_usd == 0.0
            await session.commit()

        assert await _drain(worker) == 8
        async with SessionLocal() as session:
            graph = await session.get(MediaAssetGraph, first_id)
            assert graph is not None and graph.status == "completed"
            nodes = {
                row.logical_key: row
                for row in (
                    await session.scalars(
                        select(MediaAssetNode).where(MediaAssetNode.graph_id == first_id)
                    )
                ).all()
            }
            assert nodes["waveform"].media_type == "image/png"
            assert nodes["export"].media_type == "audio/wav"
            assert all(row.status == "completed" for row in nodes.values())
            align_2_checksum = nodes["align-002"].checksum
            final_checksum = nodes["export"].checksum
            master_step = await session.scalar(
                select(MediaRenderStep).where(
                    MediaRenderStep.graph_id == first_id,
                    MediaRenderStep.target_node_id == nodes["master"].id,
                )
            )
            assert master_step is not None
            analysis = (master_step.result_metadata or {}).get("qa", {}).get(
                "audio_analysis"
            )
            assert isinstance(analysis, dict) and analysis["passed"] is True
            asset = await session.get(StudioAsset, asset_id)
            assert asset is not None and asset.current_revision == 2
            assert asset.media_type == "audio/wav"
            revised, affected = await create_partial_media_revision(
                session,
                graph=graph,
                created_by_id=user_id,
                node_parameter_updates={"align-001": {"offset_ms": 500}},
                idempotency_key="phase36g-audio-revision-2",
            )
            revised_id = revised.id
            assert affected == (
                "align-001",
                "mix",
                "master",
                "waveform",
                "export",
            )
            await session.commit()

        async with SessionLocal() as session:
            revised_nodes = {
                row.logical_key: row
                for row in (
                    await session.scalars(
                        select(MediaAssetNode).where(
                            MediaAssetNode.graph_id == revised_id
                        )
                    )
                ).all()
            }
            assert revised_nodes["align-002"].status == "completed"
            assert revised_nodes["align-002"].checksum == align_2_checksum
            assert any(
                item.get("type") == "reused-render"
                for item in revised_nodes["align-002"].provenance
            )
            steps = list(
                (
                    await session.scalars(
                        select(MediaRenderStep).where(
                            MediaRenderStep.graph_id == revised_id
                        )
                    )
                ).all()
            )
            assert len(steps) == 5

        assert await _drain(worker) == 5
        async with SessionLocal() as session:
            revised = await session.get(MediaAssetGraph, revised_id)
            assert revised is not None and revised.status == "completed"
            export = await session.scalar(
                select(MediaAssetNode).where(
                    MediaAssetNode.graph_id == revised_id,
                    MediaAssetNode.logical_key == "export",
                )
            )
            assert export is not None and export.checksum != final_checksum
            asset = await session.get(StudioAsset, asset_id)
            assert asset is not None and asset.current_revision == 3
            assert int(
                await session.scalar(
                    select(func.count())
                    .select_from(StudioAssetRevision)
                    .where(StudioAssetRevision.asset_id == asset_id)
                )
                or 0
            ) == 3
    finally:
        await _cleanup_org(org_id)


@pytest.mark.asyncio
async def test_audio_pipeline_idempotency_rejects_source_or_timeline_substitution(
    tmp_path: Path,
) -> None:
    org_id, user_id, _, _ = await _seed_actor_and_studio()
    store = LocalMediaObjectStore(tmp_path / "objects")
    sources = await _seed_sources(org_id=org_id, user_id=user_id, store=store)
    try:
        async with SessionLocal() as session:
            first = await create_local_audio_pipeline(
                session,
                scope=MediaGraphScope(organization_id=org_id, created_by_id=user_id),
                plan=_plan(),
                sources=(
                    LocalAudioSourceBinding(sources[0]),
                    LocalAudioSourceBinding(sources[1], offset_ms=250),
                ),
                idempotency_key="phase36g-audio-idempotent",
            )
            await session.commit()
        async with SessionLocal() as session:
            same = await create_local_audio_pipeline(
                session,
                scope=MediaGraphScope(organization_id=org_id, created_by_id=user_id),
                plan=_plan(),
                sources=(
                    LocalAudioSourceBinding(sources[0]),
                    LocalAudioSourceBinding(sources[1], offset_ms=250),
                ),
                idempotency_key="phase36g-audio-idempotent",
            )
            assert same.graph_id == first.graph_id
            with pytest.raises(AudioPipelineError, match="conflicts"):
                await create_local_audio_pipeline(
                    session,
                    scope=MediaGraphScope(
                        organization_id=org_id, created_by_id=user_id
                    ),
                    plan=_plan(),
                    sources=(
                        LocalAudioSourceBinding(sources[0]),
                        LocalAudioSourceBinding(sources[1], offset_ms=500),
                    ),
                    idempotency_key="phase36g-audio-idempotent",
                )
    finally:
        await _cleanup_org(org_id)


@pytest.mark.asyncio
async def test_audio_pipeline_rejects_cross_tenant_source(tmp_path: Path) -> None:
    org_a, user_a, _, _ = await _seed_actor_and_studio()
    org_b, user_b, _, _ = await _seed_actor_and_studio()
    store = LocalMediaObjectStore(tmp_path / "objects")
    source_b = (
        await _seed_sources(org_id=org_b, user_id=user_b, store=store, count=1)
    )[0]
    try:
        async with SessionLocal() as session:
            with pytest.raises(AudioPipelineError, match="another organization"):
                await create_local_audio_pipeline(
                    session,
                    scope=MediaGraphScope(
                        organization_id=org_a, created_by_id=user_a
                    ),
                    plan=_plan(source_count=1),
                    sources=(LocalAudioSourceBinding(source_b),),
                    idempotency_key="phase36g-cross-tenant",
                )
    finally:
        await _cleanup_org(org_a)
        await _cleanup_org(org_b)


@pytest.mark.asyncio
async def test_audio_render_lease_recovery_rejects_stale_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, user_id, _, _ = await _seed_actor_and_studio()
    store = LocalMediaObjectStore(tmp_path / "objects")
    monkeypatch.setattr(settings, "MEDIA_RENDER_TEMP_ROOT", str(tmp_path / "render"))
    source = (
        await _seed_sources(org_id=org_id, user_id=user_id, store=store, count=1)
    )[0]
    worker_a = MediaRenderWorker(
        store=store,
        runtime=FakeAudioRuntime(),  # type: ignore[arg-type]
        worker_id="phase36g-worker-a",
    )
    worker_b = MediaRenderWorker(
        store=store,
        runtime=FakeAudioRuntime(),  # type: ignore[arg-type]
        worker_id="phase36g-worker-b",
    )
    try:
        async with SessionLocal() as session:
            await create_local_audio_pipeline(
                session,
                scope=MediaGraphScope(organization_id=org_id, created_by_id=user_id),
                plan=_plan(source_count=1),
                sources=(LocalAudioSourceBinding(source),),
                idempotency_key="phase36g-audio-fencing",
            )
            await session.commit()
        claim_a = await worker_a.claim()
        assert claim_a is not None
        async with SessionLocal() as session:
            step = await session.get(MediaRenderStep, claim_a.step_id)
            assert step is not None and step.operation == "audio_cleanup"
            step.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        claim_b = await worker_b.claim()
        assert claim_b is not None
        assert claim_b.step_id == claim_a.step_id
        assert claim_b.fencing_token > claim_a.fencing_token
        with pytest.raises(MediaRenderLeaseLost):
            await worker_a.renew(claim_a)
        await worker_b.execute(claim_b)
        async with SessionLocal() as session:
            step = await session.get(MediaRenderStep, claim_b.step_id)
            assert step is not None and step.status == "completed"
            assert step.attempts == 2
            assert step.fencing_token == claim_b.fencing_token
    finally:
        await _cleanup_org(org_id)
