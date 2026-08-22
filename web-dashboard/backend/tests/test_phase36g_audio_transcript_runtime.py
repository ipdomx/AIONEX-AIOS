from __future__ import annotations

import io
import json
import wave
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select

from app.db.base import SessionLocal
from app.db.models import (
    AudioTranscriptExecution,
    MediaAssetGraph,
    MediaAssetNode,
    Organization,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    User,
)
from app.services.audio_transcript_pipeline import (
    AudioTranscriptPipelineError,
    create_audio_transcript_pipeline,
)
from app.services.audio_transcript_providers import ProviderDiarizedSegmentResult
from app.services.audio_transcript_runtime import (
    AudioTranscriptExecutionAuthority,
    AudioTranscriptExecutionError,
    AudioTranscriptLeaseLost,
    arm_audio_transcript_execution,
    audio_transcript_execution_snapshot,
)
from app.services.media_graph_runtime import MediaGraphScope
from app.services.media_storage import LocalMediaObjectStore


class Scope:
    def __init__(
        self,
        org: Organization,
        user: User,
        job: StudioJob,
        asset: StudioAsset,
        source_graph_id: str,
        source_node_id: str,
    ) -> None:
        self.org = org
        self.user = user
        self.job = job
        self.asset = asset
        self.source_graph_id = source_graph_id
        self.source_node_id = source_node_id


async def seed_scope(tag: str, store: LocalMediaObjectStore) -> Scope:
    suffix = uuid4().hex[:10]
    source_buffer = io.BytesIO()
    with wave.open(source_buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(48_000)
        writer.writeframes(b"\x00\x00" * 240_000)
    source_body = source_buffer.getvalue()
    stored = store.put_bytes(
        f"fixtures/{suffix}/source.wav",
        source_body,
        "audio/wav",
        metadata={"synthetic": "true"},
    )
    async with SessionLocal() as session:
        org = Organization(
            name=f"P36G Transcript {tag}",
            slug=f"p36g-transcript-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(org)
        await session.flush()
        user = User(
            organization_id=org.id,
            role_id=None,
            email=f"p36g-transcript-{tag}-{suffix}@example.com",
            name="Phase36G Transcript Owner",
            password_hash="unused",
            status="active",
        )
        session.add(user)
        await session.flush()
        job = StudioJob(
            organization_id=org.id,
            workspace_id=None,
            project_id=None,
            requested_by_id=user.id,
            department="audio",
            output_kind="transcript",
            title="P36G governed transcript",
            brief="Create a private transcript package with hash-only public evidence.",
            language="en-US",
            style="governed",
            provider_mode="provider_selected",
            status="completed",
            progress=100,
            safety_status="passed",
            request_metadata={"synthetic": True},
            result_metadata={},
            max_attempts=1,
        )
        session.add(job)
        await session.flush()
        asset = StudioAsset(
            organization_id=org.id,
            job_id=job.id,
            project_id=None,
            created_by_id=user.id,
            department="audio",
            asset_type="transcript",
            title="P36G governed transcript",
            filename="transcript-plan.zip",
            media_type="application/zip",
            storage_path="synthetic/transcript-plan.zip",
            checksum="a" * 64,
            size_bytes=1,
            status="active",
            current_revision=1,
            asset_metadata={"render_status": "planned"},
        )
        session.add(asset)
        await session.flush()
        session.add(
            StudioAssetRevision(
                organization_id=org.id,
                asset_id=asset.id,
                job_id=job.id,
                created_by_id=user.id,
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
        source_graph = MediaAssetGraph(
            organization_id=org.id,
            workspace_id=None,
            project_id=None,
            studio_job_id=None,
            studio_asset_id=None,
            created_by_id=user.id,
            title="Synthetic governed speech fixture",
            asset_kind="audio",
            output_profile="audio-wav-pcm",
            status="completed",
            graph_version=1,
            idempotency_key=f"source-graph-{suffix}",
            graph_checksum="b" * 64,
            graph_metadata={"synthetic": True},
            rights_metadata={},
            provenance=[{"type": "synthetic-test-fixture"}],
        )
        session.add(source_graph)
        await session.flush()
        source_node = MediaAssetNode(
            graph_id=source_graph.id,
            organization_id=org.id,
            created_by_id=user.id,
            logical_key="source-audio",
            revision=1,
            node_type="audio-source",
            media_type="audio/wav",
            status="completed",
            storage_backend=stored.backend,
            storage_key=stored.key,
            checksum=stored.sha256,
            size_bytes=stored.size_bytes,
            idempotency_key=f"source-node-{suffix}",
            source_metadata={
                "duration_ms": 5_000,
                "sample_rate_hz": 48_000,
                "channels": 1,
            },
            prompt_metadata={},
            rights_metadata={},
            provenance=[{"type": "synthetic-test-fixture"}],
            scene_metadata={},
            timeline_metadata={"duration_ms": 5_000},
            operation_metadata={},
        )
        session.add(source_node)
        await session.commit()
        return Scope(org, user, job, asset, source_graph.id, source_node.id)


async def cleanup_scope(scope: Scope) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(Organization).where(Organization.id == scope.org.id)
        )
        await session.commit()


async def create_pipeline(
    scope: Scope,
    *,
    key: str | None = None,
    operation: str = "transcribe",
):
    async with SessionLocal() as session:
        pipeline = await create_audio_transcript_pipeline(
            session,
            scope=MediaGraphScope(
                organization_id=scope.org.id,
                created_by_id=scope.user.id,
                studio_job_id=scope.job.id,
                studio_asset_id=scope.asset.id,
            ),
            source_node_id=scope.source_node_id,
            language="en-US",
            operation=operation,
            idempotency_key=key or f"transcript-pipeline-{uuid4()}",
            max_cost_usd=0.01,
            source_duration_ms=5_000,
            source_sample_rate_hz=48_000,
            source_channels=1,
        )
        await session.commit()
        return pipeline


async def expire(execution_id: str) -> None:
    async with SessionLocal() as session:
        row = await session.get(AudioTranscriptExecution, execution_id)
        assert row is not None
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()


@pytest.mark.asyncio
async def test_transcript_execution_is_planned_idempotent_and_cannot_claim_before_arm(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("arm", store)
    try:
        first = await create_pipeline(scope, key="phase36g-transcript-idempotency")
        second = await create_pipeline(scope, key="phase36g-transcript-idempotency")
        assert first == second
        async with SessionLocal() as session:
            with pytest.raises(AudioTranscriptPipelineError, match="conflicts"):
                await create_audio_transcript_pipeline(
                    session,
                    scope=MediaGraphScope(
                        organization_id=scope.org.id,
                        created_by_id=scope.user.id,
                        studio_job_id=scope.job.id,
                        studio_asset_id=scope.asset.id,
                    ),
                    source_node_id=scope.source_node_id,
                    language="ar-EG",
                    idempotency_key="phase36g-transcript-idempotency",
                    max_cost_usd=0.01,
                    source_duration_ms=5_000,
                    source_sample_rate_hz=48_000,
                    source_channels=1,
                )
        authority = AudioTranscriptExecutionAuthority(
            store=store,
            worker_id="transcript-worker-a",
            lease_seconds=30,
        )
        assert await authority.claim() is None
        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, first.execution_id)
            assert row is not None
            assert row.status == "planned"
            assert row.attempts == 0 and row.max_attempts == 1
            assert row.provider_state == "not_started"
            assert row.estimated_cost_usd == pytest.approx(0.00025)
            assert row.max_cost_usd == pytest.approx(0.01)
            with pytest.raises(AudioTranscriptExecutionError, match="approval"):
                await arm_audio_transcript_execution(
                    session,
                    execution_id=row.id,
                    organization_id=scope.org.id,
                    approved_max_cost_usd=0.009,
                )
            await session.rollback()
        async with SessionLocal() as session:
            row = await arm_audio_transcript_execution(
                session,
                execution_id=first.execution_id,
                organization_id=scope.org.id,
                approved_max_cost_usd=0.01,
            )
            assert row.status == "queued" and row.armed_at is not None
            await session.commit()
        claim = await authority.claim()
        assert claim is not None and claim.fencing_token == 1
        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, first.execution_id)
            assert row is not None
            assert row.status == "running"
            assert row.attempts == 0
        await authority.mark_submission_started(claim)
        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, first.execution_id)
            assert row is not None
            assert row.attempts == 1 and row.provider_state == "submitting"
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_expired_lease_before_submission_is_reclaimed_without_attempt_increment(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("reclaim-before-submit", store)
    try:
        pipeline = await create_pipeline(scope)
        async with SessionLocal() as session:
            await arm_audio_transcript_execution(
                session,
                execution_id=pipeline.execution_id,
                organization_id=scope.org.id,
                approved_max_cost_usd=0.01,
            )
            await session.commit()
        worker_a = AudioTranscriptExecutionAuthority(
            store=store, worker_id="worker-a", lease_seconds=30
        )
        worker_b = AudioTranscriptExecutionAuthority(
            store=store, worker_id="worker-b", lease_seconds=30
        )
        first = await worker_a.claim()
        assert first is not None and first.fencing_token == 1
        await expire(pipeline.execution_id)
        second = await worker_b.claim()
        assert second is not None and second.fencing_token == 2
        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, pipeline.execution_id)
            assert row is not None
            assert row.attempts == 0
            assert row.lease_owner == "worker-b"
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_expired_lease_after_submission_becomes_needs_review_without_resubmit(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("ambiguous", store)
    try:
        pipeline = await create_pipeline(scope)
        async with SessionLocal() as session:
            await arm_audio_transcript_execution(
                session,
                execution_id=pipeline.execution_id,
                organization_id=scope.org.id,
                approved_max_cost_usd=0.01,
            )
            await session.commit()
        worker_a = AudioTranscriptExecutionAuthority(
            store=store, worker_id="worker-a", lease_seconds=30
        )
        worker_b = AudioTranscriptExecutionAuthority(
            store=store, worker_id="worker-b", lease_seconds=30
        )
        claim = await worker_a.claim()
        assert claim is not None
        await worker_a.mark_submission_started(claim)
        await expire(pipeline.execution_id)
        assert await worker_b.claim() is None
        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, pipeline.execution_id)
            assert row is not None
            assert row.status == "needs_review"
            assert row.provider_state == "submitting"
            assert row.attempts == 1
            assert row.error_code == "provider_submission_ambiguous"
            assert row.lease_owner is None and row.lease_token is None
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_reclaimed_transcript_lease_fences_stale_worker(tmp_path: Path) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("fencing", store)
    try:
        pipeline = await create_pipeline(scope)
        async with SessionLocal() as session:
            await arm_audio_transcript_execution(
                session,
                execution_id=pipeline.execution_id,
                organization_id=scope.org.id,
                approved_max_cost_usd=0.01,
            )
            await session.commit()
        worker_a = AudioTranscriptExecutionAuthority(
            store=store, worker_id="worker-a", lease_seconds=30
        )
        worker_b = AudioTranscriptExecutionAuthority(
            store=store, worker_id="worker-b", lease_seconds=30
        )
        stale = await worker_a.claim()
        assert stale is not None
        await expire(pipeline.execution_id)
        current = await worker_b.claim()
        assert current is not None and current.fencing_token == 2
        with pytest.raises(AudioTranscriptLeaseLost):
            await worker_a.mark_submission_started(stale)
        await worker_b.mark_submission_started(current)
        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, pipeline.execution_id)
            assert row is not None and row.attempts == 1
            assert row.fencing_token == 2 and row.lease_owner == "worker-b"
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_completed_transcript_creates_private_package_captions_studio_revision_and_hash_only_public_evidence(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("complete", store)
    raw_text = "AIONEX keeps the private transcript inside governed storage."
    try:
        pipeline = await create_pipeline(scope)
        async with SessionLocal() as session:
            await arm_audio_transcript_execution(
                session,
                execution_id=pipeline.execution_id,
                organization_id=scope.org.id,
                approved_max_cost_usd=0.01,
            )
            await session.commit()
        authority = AudioTranscriptExecutionAuthority(
            store=store, worker_id="worker-a", lease_seconds=30
        )
        claim = await authority.claim()
        assert claim is not None
        await authority.mark_submission_started(claim)
        result = await authority.complete_text(
            claim,
            text=raw_text,
            provider_request_id="req-private-transcript",
            provider_response_metadata={
                "duration_ms": 5_000,
                "text": "must-not-persist",
                "signed_url": "https://must-not-persist.example",
            },
            usage_metadata={
                "estimated_cost_usd": 0.00025,
                "actual_cost_known": False,
                "api_key": "must-not-persist",
            },
            actual_cost_usd=None,
            cost_basis="official_estimated_per_minute",
        )
        assert result["status"] == "completed"
        assert len(result["stored_object_keys"]) == 4
        package_key = next(
            key for key in result["stored_object_keys"] if key.endswith(".zip")
        )
        package_path = store.root / package_key
        assert package_path.is_file()
        with zipfile.ZipFile(package_path) as archive:
            assert set(archive.namelist()) == {
                "transcript/private-transcript.json",
                "captions/captions.vtt",
                "captions/captions.srt",
                "captions/manifest.json",
            }
            private = json.loads(
                archive.read("transcript/private-transcript.json").decode("utf-8")
            )
            assert private["segments"][0]["text"] == raw_text
            assert raw_text in archive.read("captions/captions.vtt").decode("utf-8")
            assert raw_text in archive.read("captions/captions.srt").decode("utf-8")

        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, pipeline.execution_id)
            graph = await session.get(MediaAssetGraph, pipeline.graph_id)
            target = await session.get(MediaAssetNode, pipeline.target_node_id)
            asset = await session.get(StudioAsset, scope.asset.id)
            revision_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(StudioAssetRevision)
                    .where(StudioAssetRevision.asset_id == scope.asset.id)
                )
                or 0
            )
            assert row is not None and row.status == "completed"
            assert row.provider_state == "completed" and row.attempts == 1
            assert row.actual_cost_usd is None
            assert row.transcript_text_sha256
            assert row.transcript_characters == len(raw_text)
            assert row.segment_count == 1 and row.speaker_count == 1
            assert row.provider_response_metadata == {"duration_ms": 5_000}
            assert "api_key" not in row.usage_metadata
            assert graph is not None and graph.status == "completed"
            assert (
                graph.graph_metadata["transcript"]["raw_transcript_returned"] is False
            )
            assert target is not None and target.status == "completed"
            assert target.media_type == "application/zip"
            assert asset is not None and asset.current_revision == 2
            assert revision_count == 2
            public = await audio_transcript_execution_snapshot(
                session,
                execution_id=pipeline.execution_id,
                organization_id=scope.org.id,
            )
            rendered = repr(public)
            assert public["status"] == "completed"
            assert public["transcript"]["text_sha256"] == row.transcript_text_sha256
            assert public["raw_transcript_returned"] is False
            assert raw_text not in rendered
            assert "req-private-transcript" not in rendered
            assert package_key not in rendered
            assert "must-not-persist" not in rendered
    finally:
        await cleanup_scope(scope)



@pytest.mark.asyncio
async def test_completed_diarization_pseudonymizes_provider_labels_and_materializes_timed_captions(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("diarization-complete", store)
    raw_labels = ("provider-alpha-private", "provider-beta-private")
    try:
        pipeline = await create_pipeline(scope, operation="diarize")
        assert pipeline.operation == "diarize"
        assert pipeline.model == "gpt-4o-transcribe-diarize"
        assert pipeline.response_format == "diarized_json"
        assert pipeline.estimated_cost_usd == pytest.approx(0.0005)
        async with SessionLocal() as session:
            row = await arm_audio_transcript_execution(
                session,
                execution_id=pipeline.execution_id,
                organization_id=scope.org.id,
                approved_max_cost_usd=0.01,
            )
            assert row.operation == "diarize"
            await session.commit()
        authority = AudioTranscriptExecutionAuthority(
            store=store, worker_id="diarization-worker-a", lease_seconds=30
        )
        claim = await authority.claim()
        assert claim is not None
        await authority.mark_submission_started(claim)
        result = await authority.complete_diarization(
            claim,
            segments=(
                ProviderDiarizedSegmentResult(
                    provider_segment_id="provider-segment-a",
                    speaker_label=raw_labels[0],
                    start_seconds=0.0,
                    end_seconds=1.5,
                    text="First governed speaker.",
                ),
                ProviderDiarizedSegmentResult(
                    provider_segment_id="provider-segment-b",
                    speaker_label=raw_labels[1],
                    start_seconds=1.5,
                    end_seconds=3.2,
                    text="Second governed speaker.",
                ),
                ProviderDiarizedSegmentResult(
                    provider_segment_id="provider-segment-c",
                    speaker_label=raw_labels[0],
                    start_seconds=3.2,
                    end_seconds=5.0,
                    text="First speaker returns.",
                ),
            ),
            provider_request_id="req-private-diarization",
            provider_response_metadata={
                "duration_ms": 5_000,
                "raw_speaker_label": raw_labels[0],
                "segments": [{"speaker": raw_labels[1]}],
                "raw_speaker_labels_returned": False,
            },
            usage_metadata={
                "provider_usage_type": "duration",
                "provider_usage_seconds": 5.0,
                "estimated_cost_usd": 0.0005,
                "actual_cost_known": False,
            },
            actual_cost_usd=None,
            cost_basis="official_estimated_per_minute",
        )
        assert result["status"] == "completed"
        assert result["operation"] == "diarize"
        assert result["segment_count"] == 3
        assert result["speaker_count"] == 2
        package_key = next(
            key for key in result["stored_object_keys"] if key.endswith(".zip")
        )
        package_path = store.root / package_key
        with zipfile.ZipFile(package_path) as archive:
            private_body = archive.read("transcript/private-transcript.json").decode(
                "utf-8"
            )
            private = json.loads(private_body)
            webvtt = archive.read("captions/captions.vtt").decode("utf-8")
            srt = archive.read("captions/captions.srt").decode("utf-8")
            manifest = json.loads(
                archive.read("captions/manifest.json").decode("utf-8")
            )
        assert [item["speaker_key"] for item in private["segments"]] == [
            "speaker-001",
            "speaker-002",
            "speaker-001",
        ]
        assert [item["segment_id"] for item in private["segments"]] == [
            "segment-001",
            "segment-002",
            "segment-003",
        ]
        assert private["diarization_enabled"] is True
        assert "00:00:00.000 --> 00:00:01.500" in webvtt
        assert "00:00:01,500 --> 00:00:03,200" in srt
        assert "[speaker-001]" in webvtt and "[speaker-002]" in webvtt
        assert manifest["diarization_enabled"] is True
        assert manifest["speaker_count"] == 2
        assert manifest["segment_count"] == 3
        assert manifest["raw_speaker_labels_returned"] is False
        combined = repr(
            {
                "private": private,
                "webvtt": webvtt,
                "srt": srt,
                "manifest": manifest,
            }
        )
        for raw_label in raw_labels:
            assert raw_label not in combined

        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, pipeline.execution_id)
            graph = await session.get(MediaAssetGraph, pipeline.graph_id)
            asset = await session.get(StudioAsset, scope.asset.id)
            revision_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(StudioAssetRevision)
                    .where(StudioAssetRevision.asset_id == scope.asset.id)
                )
                or 0
            )
            assert row is not None and row.status == "completed"
            assert row.operation == "diarize"
            assert row.model == "gpt-4o-transcribe-diarize"
            assert row.response_format == "diarized_json"
            assert row.attempts == 1 and row.max_attempts == 1
            assert row.segment_count == 3 and row.speaker_count == 2
            assert row.actual_cost_usd is None
            assert row.provider_response_metadata["pseudonymous_speaker_count"] == 2
            persisted = repr(
                {
                    "provider": row.provider_response_metadata,
                    "usage": row.usage_metadata,
                    "graph": graph.graph_metadata if graph else None,
                    "asset": asset.asset_metadata if asset else None,
                }
            )
            for raw_label in raw_labels:
                assert raw_label not in persisted
            assert graph is not None and graph.status == "completed"
            assert graph.graph_metadata["operation"] == "diarize"
            assert (
                graph.graph_metadata["transcript"]["speaker_keys"]
                == ["speaker-001", "speaker-002"]
            )
            assert graph.graph_metadata["raw_speaker_labels_returned"] is False
            assert asset is not None and asset.current_revision == 2
            assert revision_count == 2
            public = await audio_transcript_execution_snapshot(
                session,
                execution_id=pipeline.execution_id,
                organization_id=scope.org.id,
            )
            rendered = repr(public)
            assert public["operation"] == "diarize"
            assert public["transcript"]["segment_count"] == 3
            assert public["transcript"]["speaker_count"] == 2
            assert public["raw_transcript_returned"] is False
            for forbidden in (*raw_labels, "req-private-diarization", package_key):
                assert forbidden not in rendered
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_diarization_completion_rejects_single_speaker_without_persisting_output(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("diarization-one-speaker", store)
    try:
        pipeline = await create_pipeline(scope, operation="diarize")
        async with SessionLocal() as session:
            await arm_audio_transcript_execution(
                session,
                execution_id=pipeline.execution_id,
                organization_id=scope.org.id,
                approved_max_cost_usd=0.01,
            )
            await session.commit()
        authority = AudioTranscriptExecutionAuthority(
            store=store, worker_id="diarization-worker-a", lease_seconds=30
        )
        claim = await authority.claim()
        assert claim is not None
        await authority.mark_submission_started(claim)
        with pytest.raises(
            AudioTranscriptExecutionError, match="does not prove multi-speaker"
        ):
            await authority.complete_diarization(
                claim,
                segments=(
                    ProviderDiarizedSegmentResult(
                        provider_segment_id="provider-segment-a",
                        speaker_label="same-provider-speaker",
                        start_seconds=0.0,
                        end_seconds=2.0,
                        text="One speaker.",
                    ),
                    ProviderDiarizedSegmentResult(
                        provider_segment_id="provider-segment-b",
                        speaker_label="same-provider-speaker",
                        start_seconds=2.0,
                        end_seconds=5.0,
                        text="Still one speaker.",
                    ),
                ),
                provider_request_id="req-one-speaker",
                provider_response_metadata={},
                usage_metadata={},
                actual_cost_usd=None,
                cost_basis="official_estimated_per_minute",
            )
        async with SessionLocal() as session:
            row = await session.get(AudioTranscriptExecution, pipeline.execution_id)
            target = await session.get(MediaAssetNode, pipeline.target_node_id)
            assert row is not None and row.status == "running"
            assert row.provider_state == "submitting" and row.attempts == 1
            assert target is not None and target.status == "planned"
            assert target.storage_key is None and target.checksum is None
    finally:
        await cleanup_scope(scope)

def test_audio_transcript_schema_has_source_fencing_ambiguity_cost_and_hash_fields() -> (
    None
):
    from app.db.base import Base
    import app.db.models  # noqa: F401

    columns = set(Base.metadata.tables["audio_transcript_executions"].c.keys())
    assert {
        "status",
        "armed_at",
        "provider_state",
        "provider_submitted_at",
        "attempts",
        "max_attempts",
        "lease_token",
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "source_storage_backend",
        "source_storage_key",
        "source_checksum",
        "source_size_bytes",
        "source_media_type",
        "source_duration_ms",
        "estimated_cost_usd",
        "max_cost_usd",
        "actual_cost_usd",
        "transcript_checksum",
        "transcript_text_sha256",
        "output_storage_key",
        "output_checksum",
    } <= columns
