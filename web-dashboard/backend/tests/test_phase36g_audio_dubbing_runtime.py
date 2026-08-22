from __future__ import annotations

import io
import json
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from aios.phase36_audio_transcript import (
    GovernedAudioSource,
    TranscriptDocument,
    TranscriptSegment,
)
from app.db.base import Base, SessionLocal
from app.db.models import (
    AudioDubbingExecution,
    AudioSpeechExecution,
    MediaAssetGraph,
    MediaAssetNode,
    Organization,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    User,
)
from app.services.audio_dubbing_pipeline import (
    AudioDubbingPipelineError,
    create_audio_dubbing_pipeline,
    create_dubbing_final_pipeline,
    create_dubbing_speech_pipelines_from_private,
    finalize_dubbing_execution,
    load_private_translation,
    refresh_dubbing_speech_status,
    replace_failed_dubbing_segment,
)
from app.services.audio_dubbing_runtime import (
    AudioDubbingExecutionAuthority,
    AudioDubbingExecutionError,
    AudioDubbingLeaseLost,
    arm_audio_dubbing_execution,
    audio_dubbing_execution_snapshot,
)
from app.services.media_graph_runtime import MediaGraphScope
from app.services.media_storage import LocalMediaObjectStore
from sqlalchemy import delete, select


RUNTIME_EVIDENCE = "c" * 64
TRANSLATIONS = {
    "segment-001": "Audio gobernado uno.",
    "segment-002": "Audio gobernado dos.",
}


class Scope:
    def __init__(
        self,
        *,
        org_id: str,
        user_id: str,
        job_id: str,
        asset_id: str,
        transcript_node_id: str,
        document: TranscriptDocument,
    ) -> None:
        self.org_id = org_id
        self.user_id = user_id
        self.job_id = job_id
        self.asset_id = asset_id
        self.transcript_node_id = transcript_node_id
        self.document = document


def wav_bytes(*, seconds: float = 1.0, rate: int = 48_000) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b"\x00\x00" * int(seconds * rate) * 2)
    return output.getvalue()


def document() -> TranscriptDocument:
    source = GovernedAudioSource(
        source_sha256="a" * 64,
        locator_sha256="b" * 64,
        size_bytes=1_000,
        media_type="audio/wav",
        duration_ms=6_000,
        sample_rate_hz=48_000,
        channels=1,
    )
    return TranscriptDocument(
        source=source,
        language="en",
        segments=(
            TranscriptSegment(
                segment_id="segment-001",
                speaker_key="speaker-001",
                start_ms=0,
                end_ms=2_000,
                text="Governed private source one.",
                language="en",
                confidence=0.99,
            ),
            TranscriptSegment(
                segment_id="segment-002",
                speaker_key="speaker-002",
                start_ms=2_500,
                end_ms=5_000,
                text="Governed private source two.",
                language="en",
                confidence=0.98,
            ),
        ),
        diarization_enabled=True,
    )


def voice_bindings() -> dict[str, dict[str, object]]:
    return {
        "speaker-001": {
            "voice": "marin",
            "runtime_evidence_sha256": RUNTIME_EVIDENCE,
            "custom_voice": False,
            "voice_clone": False,
            "voice_transformation": False,
        },
        "speaker-002": {
            "voice": "cedar",
            "runtime_evidence_sha256": RUNTIME_EVIDENCE,
            "custom_voice": False,
            "voice_clone": False,
            "voice_transformation": False,
        },
    }


async def seed_scope(tag: str, store: LocalMediaObjectStore) -> Scope:
    suffix = uuid4().hex[:10]
    doc = document()
    private = (json.dumps(doc.private_payload(), sort_keys=True) + "\n").encode()
    stored = store.put_bytes(
        f"fixtures/{suffix}/private-transcript.json",
        private,
        "application/json",
        metadata={"private": "true"},
    )
    async with SessionLocal() as session:
        org = Organization(
            name=f"P36G Dubbing {tag}",
            slug=f"p36g-dubbing-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(org)
        await session.flush()
        user = User(
            organization_id=org.id,
            role_id=None,
            email=f"p36g-dubbing-{tag}-{suffix}@example.invalid",
            name="Phase36G Dubbing Owner",
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
            output_kind="audio",
            title="P36G complete stock-voice dubbing",
            brief="Translate private segments and render stock-voice dubbing.",
            language="es",
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
            asset_type="audio",
            title="P36G complete stock-voice dubbing",
            filename="dubbing-plan.zip",
            media_type="application/zip",
            storage_path="synthetic/dubbing-plan.zip",
            checksum="d" * 64,
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
        graph = MediaAssetGraph(
            organization_id=org.id,
            workspace_id=None,
            project_id=None,
            studio_job_id=None,
            studio_asset_id=None,
            created_by_id=user.id,
            title="Governed private source transcript",
            asset_kind="transcript",
            output_profile="transcript-package-v1",
            status="completed",
            graph_version=1,
            idempotency_key=f"dubbing-source-graph-{suffix}",
            graph_checksum="e" * 64,
            graph_metadata={"synthetic": True},
            rights_metadata={
                "speaker_identity_mode": "pseudonymous",
                "voice_clone": False,
            },
            provenance=[{"type": "governed-private-transcript"}],
        )
        session.add(graph)
        await session.flush()
        node = MediaAssetNode(
            graph_id=graph.id,
            organization_id=org.id,
            created_by_id=user.id,
            logical_key="transcript-package",
            revision=1,
            node_type="transcript-package",
            media_type="application/json",
            status="completed",
            storage_backend=stored.backend,
            storage_key=stored.key,
            checksum=stored.sha256,
            size_bytes=stored.size_bytes,
            idempotency_key=f"dubbing-source-node-{suffix}",
            source_metadata={"transcript_checksum": doc.checksum},
            prompt_metadata={},
            rights_metadata={
                "raw_transcript_private": True,
                "speaker_identity_mode": "pseudonymous",
            },
            provenance=[{"type": "governed-private-transcript"}],
            scene_metadata={},
            timeline_metadata={"duration_ms": doc.source.duration_ms},
            operation_metadata={"transcript_checksum": doc.checksum},
        )
        session.add(node)
        await session.commit()
        return Scope(
            org_id=org.id,
            user_id=user.id,
            job_id=job.id,
            asset_id=asset.id,
            transcript_node_id=node.id,
            document=doc,
        )


async def cleanup(scope: Scope) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(Organization).where(Organization.id == scope.org_id)
        )
        await session.commit()


async def create_pipeline(scope: Scope, *, key: str = "phase36g-dubbing-test"):
    async with SessionLocal() as session:
        result = await create_audio_dubbing_pipeline(
            session,
            scope=MediaGraphScope(
                organization_id=scope.org_id,
                created_by_id=scope.user_id,
                studio_job_id=scope.job_id,
                studio_asset_id=scope.asset_id,
            ),
            source_transcript_node_id=scope.transcript_node_id,
            document=scope.document,
            target_language="es",
            voice_bindings=voice_bindings(),
            output_profile_id="wav-pcm-48k-stereo",
            idempotency_key=key,
            max_translation_cost_usd=0.005,
            per_segment_speech_cap_usd=0.02,
            max_total_cost_usd=0.05,
        )
        await session.commit()
        return result


async def complete_translation(
    scope: Scope,
    store: LocalMediaObjectStore,
    *,
    key: str,
) -> str:
    result = await create_pipeline(scope, key=key)
    async with SessionLocal() as session:
        await arm_audio_dubbing_execution(
            session,
            execution_id=result.execution_id,
            organization_id=scope.org_id,
            approved_max_total_cost_usd=0.05,
        )
        await session.commit()
    authority = AudioDubbingExecutionAuthority(
        store=store,
        worker_id="dubbing-worker-a",
        lease_seconds=30,
    )
    claim = await authority.claim()
    assert claim is not None
    await authority.mark_submission_started(claim)
    completed = await authority.complete_translation(
        claim,
        document=scope.document,
        translations=TRANSLATIONS,
        provider_request_id="req-private-translation",
        provider_response_metadata={
            "segment_count": 2,
            "translation_text": "must-not-persist",
            "authorization": "must-not-persist",
        },
        usage_metadata={
            "input_tokens": 100,
            "output_tokens": 80,
            "actual_cost_known": True,
            "api_key": "must-not-persist",
        },
        actual_cost_usd=0.000116,
        cost_basis="provider_usage_official_rates",
    )
    assert completed["status"] == "translated"
    return result.execution_id


@pytest.mark.asyncio
async def test_dubbing_execution_is_idempotent_unarmed_and_exact_cost_gated(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("arm", store)
    try:
        first = await create_pipeline(scope, key="phase36g-dubbing-arm")
        same = await create_pipeline(scope, key="phase36g-dubbing-arm")
        assert same == first
        authority = AudioDubbingExecutionAuthority(
            store=store,
            worker_id="dubbing-worker-a",
            lease_seconds=30,
        )
        assert await authority.claim() is None
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, first.execution_id)
            assert row is not None and row.status == "planned"
            assert row.attempts == 0 and row.max_attempts == 1
            assert row.estimated_translation_cost_usd <= row.max_translation_cost_usd
            assert row.speech_cost_upper_bound_usd == pytest.approx(0.04)
            assert row.max_total_cost_usd == pytest.approx(0.05)
            with pytest.raises(AudioDubbingExecutionError, match="approval"):
                await arm_audio_dubbing_execution(
                    session,
                    execution_id=row.id,
                    organization_id=scope.org_id,
                    approved_max_total_cost_usd=0.049,
                )
            await session.rollback()
        async with SessionLocal() as session:
            row = await arm_audio_dubbing_execution(
                session,
                execution_id=first.execution_id,
                organization_id=scope.org_id,
                approved_max_total_cost_usd=0.05,
            )
            assert row.status == "queued" and row.armed_at is not None
            await session.commit()
        claim = await authority.claim()
        assert claim is not None and claim.fencing_token == 1
        await authority.mark_submission_started(claim)
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, first.execution_id)
            assert row is not None
            assert row.attempts == 1 and row.provider_state == "submitting"
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_expired_pre_submit_dubbing_lease_is_reclaimed_and_fences_stale_worker(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("fencing", store)
    try:
        result = await create_pipeline(scope, key="phase36g-dubbing-fencing")
        async with SessionLocal() as session:
            await arm_audio_dubbing_execution(
                session,
                execution_id=result.execution_id,
                organization_id=scope.org_id,
                approved_max_total_cost_usd=0.05,
            )
            await session.commit()
        worker_a = AudioDubbingExecutionAuthority(
            store=store, worker_id="worker-a", lease_seconds=30
        )
        worker_b = AudioDubbingExecutionAuthority(
            store=store, worker_id="worker-b", lease_seconds=30
        )
        stale = await worker_a.claim()
        assert stale is not None and stale.fencing_token == 1
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, result.execution_id)
            assert row is not None
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        current = await worker_b.claim()
        assert current is not None and current.fencing_token == 2
        with pytest.raises(AudioDubbingLeaseLost):
            await worker_a.mark_submission_started(stale)
        await worker_b.mark_submission_started(current)
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, result.execution_id)
            assert row is not None and row.attempts == 1
            assert row.lease_owner == "worker-b" and row.fencing_token == 2
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_expired_submitting_translation_becomes_needs_review_without_second_claim(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("ambiguous", store)
    try:
        result = await create_pipeline(scope, key="phase36g-dubbing-ambiguous")
        async with SessionLocal() as session:
            await arm_audio_dubbing_execution(
                session,
                execution_id=result.execution_id,
                organization_id=scope.org_id,
                approved_max_total_cost_usd=0.05,
            )
            await session.commit()
        worker_a = AudioDubbingExecutionAuthority(
            store=store, worker_id="worker-a", lease_seconds=30
        )
        worker_b = AudioDubbingExecutionAuthority(
            store=store, worker_id="worker-b", lease_seconds=30
        )
        claim = await worker_a.claim()
        assert claim is not None
        await worker_a.mark_submission_started(claim)
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, result.execution_id)
            assert row is not None
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        assert await worker_b.claim() is None
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, result.execution_id)
            assert row is not None
            assert row.status == "needs_review"
            assert row.provider_state == "ambiguous"
            assert row.attempts == 1
            assert row.error_code == "provider_submission_ambiguous"
            assert row.lease_owner is None and row.lease_token is None
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_private_translation_spawns_two_unsubmitted_stock_speech_pipelines_without_public_leaks(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("translation", store)
    try:
        execution_id = await complete_translation(
            scope,
            store,
            key="phase36g-dubbing-private-translation",
        )
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None and row.status == "translated"
            assert row.actual_translation_cost_usd == pytest.approx(0.000116)
            assert row.provider_response_metadata == {"segment_count": 2}
            assert "api_key" not in row.usage_metadata
            assert row.translation_storage_key and row.translation_checksum
            document_loaded, translations = load_private_translation(
                store=store,
                storage_key=row.translation_storage_key,
                checksum=row.translation_checksum,
                size_bytes=int(row.translation_size_bytes or 0),
            )
            assert document_loaded.checksum == scope.document.checksum
            assert translations == TRANSLATIONS
            public = await audio_dubbing_execution_snapshot(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
            )
            rendered = repr(public)
            assert public["translation"]["raw_translation_returned"] is False
            assert public["raw_source_transcript_returned"] is False
            assert "Governed private source" not in rendered
            assert "Audio gobernado" not in rendered
            assert "req-private-translation" not in rendered
            assert row.translation_storage_key not in rendered
            await create_dubbing_speech_pipelines_from_private(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
                document=document_loaded,
                translations=translations,
            )
            await session.commit()
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None and row.status == "speech_running"
            assert len(row.speech_pipelines) == 2
            executions = list(
                (
                    await session.scalars(
                        select(AudioSpeechExecution).where(
                            AudioSpeechExecution.organization_id == scope.org_id
                        )
                    )
                ).all()
            )
            assert len(executions) == 2
            assert all(item.status == "queued" for item in executions)
            assert all(item.attempts == 0 and item.max_attempts == 1 for item in executions)
            assert {item.voice for item in executions} == {"marin", "cedar"}
            public = await audio_dubbing_execution_snapshot(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
            )
            assert len(public["speech_pipelines"]) == 2
            assert all(
                item["execution_id_sha256"]
                for item in public["speech_pipelines"]
            )
            assert all("speech_execution_id" not in item for item in public["speech_pipelines"])
    finally:
        await cleanup(scope)


async def mark_speech_completed(
    *,
    scope: Scope,
    store: LocalMediaObjectStore,
    execution_id: str,
) -> None:
    async with SessionLocal() as session:
        row = await session.get(AudioDubbingExecution, execution_id)
        assert row is not None
        for index, item in enumerate(row.speech_pipelines):
            speech = await session.get(AudioSpeechExecution, item["speech_execution_id"])
            graph = await session.get(MediaAssetGraph, item["speech_graph_id"])
            node = await session.get(MediaAssetNode, item["speech_final_node_id"])
            assert speech is not None and graph is not None and node is not None
            body = wav_bytes(seconds=1.0)
            stored = store.put_bytes(
                f"speech/{execution_id}/{index}.wav",
                body,
                "audio/wav",
                metadata={"synthetic": "true"},
            )
            speech.status = "completed"
            speech.provider_state = "completed"
            speech.output_duration_seconds = 1.0
            speech.output_checksum = stored.sha256
            speech.output_size_bytes = stored.size_bytes
            speech.output_storage_backend = stored.backend
            speech.output_storage_key = stored.key
            speech.completed_at = datetime.now(UTC)
            graph.status = "completed"
            node.status = "completed"
            node.media_type = "audio/wav"
            node.storage_backend = stored.backend
            node.storage_key = stored.key
            node.checksum = stored.sha256
            node.size_bytes = stored.size_bytes
            node.timeline_metadata = {"duration_seconds": 1.0}
        await session.commit()


@pytest.mark.asyncio
async def test_completed_segment_speech_opens_timing_fit_final_graph_and_finishes_studio_revision(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("final", store)
    try:
        execution_id = await complete_translation(
            scope,
            store,
            key="phase36g-dubbing-final",
        )
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None
            document_loaded, translations = load_private_translation(
                store=store,
                storage_key=str(row.translation_storage_key),
                checksum=str(row.translation_checksum),
                size_bytes=int(row.translation_size_bytes or 0),
            )
            await create_dubbing_speech_pipelines_from_private(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
                document=document_loaded,
                translations=translations,
            )
            await session.commit()
        await mark_speech_completed(
            scope=scope,
            store=store,
            execution_id=execution_id,
        )
        async with SessionLocal() as session:
            status = await refresh_dubbing_speech_status(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
            )
            assert status == "speech_completed"
            graph_id = await create_dubbing_final_pipeline(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
            )
            await session.commit()
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None and row.status == "rendering"
            assert row.final_graph_id == graph_id
            align_nodes = list(
                (
                    await session.scalars(
                        select(MediaAssetNode).where(
                            MediaAssetNode.graph_id == graph_id,
                            MediaAssetNode.node_type == "audio-alignment",
                        )
                    )
                ).all()
            )
            assert len(align_nodes) == 2
            targets = sorted(
                int(item.operation_metadata["target_duration_ms"])
                for item in align_nodes
            )
            assert targets == [2_000, 2_500]
            assert {
                item.operation_metadata["timing_fit_mode"] for item in align_nodes
            } == {"pad-to-window"}
            graph = await session.get(MediaAssetGraph, graph_id)
            final = await session.scalar(
                select(MediaAssetNode).where(
                    MediaAssetNode.graph_id == graph_id,
                    MediaAssetNode.logical_key == "export",
                )
            )
            asset = await session.get(StudioAsset, scope.asset_id)
            assert graph is not None and final is not None and asset is not None
            output = store.put_bytes(
                f"final/{execution_id}/dub.wav",
                wav_bytes(seconds=5.0),
                "audio/wav",
                metadata={"synthetic": "true"},
            )
            graph.status = "completed"
            final.status = "completed"
            final.media_type = "audio/wav"
            final.storage_backend = output.backend
            final.storage_key = output.key
            final.checksum = output.sha256
            final.size_bytes = output.size_bytes
            final.timeline_metadata = {"duration_seconds": 5.0}
            asset.current_revision = 2
            session.add(
                StudioAssetRevision(
                    organization_id=scope.org_id,
                    asset_id=asset.id,
                    job_id=scope.job_id,
                    created_by_id=scope.user_id,
                    revision_number=2,
                    filename="governed-dub.wav",
                    media_type="audio/wav",
                    storage_path=output.key,
                    checksum=output.sha256,
                    size_bytes=output.size_bytes,
                    revision_metadata={"synthetic": True},
                    status="active",
                )
            )
            result = await finalize_dubbing_execution(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
            )
            await session.commit()
            assert result["status"] == "completed"
            assert result["studio_revision"] == 2
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None and row.status == "completed"
            assert row.final_output_checksum
            assert row.actual_total_cost_usd is None
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_overlong_stock_speech_blocks_final_timing_fit_without_truncation(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("overlong", store)
    try:
        execution_id = await complete_translation(
            scope,
            store,
            key="phase36g-dubbing-overlong",
        )
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None
            doc, translations = load_private_translation(
                store=store,
                storage_key=str(row.translation_storage_key),
                checksum=str(row.translation_checksum),
                size_bytes=int(row.translation_size_bytes or 0),
            )
            await create_dubbing_speech_pipelines_from_private(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
                document=doc,
                translations=translations,
            )
            await session.commit()
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None
            for index, item in enumerate(row.speech_pipelines):
                speech = await session.get(
                    AudioSpeechExecution, item["speech_execution_id"]
                )
                graph = await session.get(MediaAssetGraph, item["speech_graph_id"])
                node = await session.get(MediaAssetNode, item["speech_final_node_id"])
                assert speech is not None and graph is not None and node is not None
                seconds = 3.0 if index == 0 else 1.0
                stored = store.put_bytes(
                    f"speech/{execution_id}/overlong-{index}.wav",
                    wav_bytes(seconds=seconds),
                    "audio/wav",
                    metadata={"synthetic": "true"},
                )
                speech.status = "completed"
                speech.provider_state = "completed"
                speech.output_duration_seconds = seconds
                graph.status = "completed"
                node.status = "completed"
                node.storage_backend = stored.backend
                node.storage_key = stored.key
                node.checksum = stored.sha256
                node.size_bytes = stored.size_bytes
                node.media_type = "audio/wav"
            await session.commit()
        async with SessionLocal() as session:
            assert (
                await refresh_dubbing_speech_status(
                    session,
                    execution_id=execution_id,
                    organization_id=scope.org_id,
                )
                == "speech_completed"
            )
            await session.commit()
        async with SessionLocal() as session:
            with pytest.raises(AudioDubbingPipelineError, match="timing window"):
                await create_dubbing_final_pipeline(
                    session,
                    execution_id=execution_id,
                    organization_id=scope.org_id,
                )
            await session.rollback()
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None
            assert row.final_graph_id is None
            assert row.status == "speech_completed"
    finally:
        await cleanup(scope)


@pytest.mark.asyncio
async def test_selective_replacement_changes_only_definitively_failed_segment(
    tmp_path: Path,
) -> None:
    store = LocalMediaObjectStore(tmp_path / "objects")
    scope = await seed_scope("replacement", store)
    try:
        execution_id = await complete_translation(
            scope,
            store,
            key="phase36g-dubbing-replacement",
        )
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None
            doc, translations = load_private_translation(
                store=store,
                storage_key=str(row.translation_storage_key),
                checksum=str(row.translation_checksum),
                size_bytes=int(row.translation_size_bytes or 0),
            )
            original = await create_dubbing_speech_pipelines_from_private(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
                document=doc,
                translations=translations,
            )
            await session.commit()
        failed = dict(original[0])
        kept = dict(original[1])
        async with SessionLocal() as session:
            speech = await session.get(
                AudioSpeechExecution, failed["speech_execution_id"]
            )
            graph = await session.get(MediaAssetGraph, failed["speech_graph_id"])
            assert speech is not None and graph is not None
            speech.status = "failed"
            speech.provider_state = "failed"
            speech.error_code = "definitive_provider_failure"
            graph.status = "failed"
            await session.commit()
        async with SessionLocal() as session:
            status = await refresh_dubbing_speech_status(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
            )
            assert status == "speech_failed"
            replacement = await replace_failed_dubbing_segment(
                session,
                execution_id=execution_id,
                organization_id=scope.org_id,
                segment_id=failed["segment_id"],
                document=doc,
                translations=translations,
            )
            await session.commit()
            assert replacement["speech_execution_id"] != failed["speech_execution_id"]
            assert replacement["replacement_generation"] == 1
        async with SessionLocal() as session:
            row = await session.get(AudioDubbingExecution, execution_id)
            assert row is not None and row.status == "speech_running"
            entries = {item["segment_id"]: item for item in row.speech_pipelines}
            assert entries[kept["segment_id"]]["speech_execution_id"] == kept[
                "speech_execution_id"
            ]
            assert len(row.replacement_history) == 1
            assert row.replacement_history[0]["segment_id"] == failed["segment_id"]
    finally:
        await cleanup(scope)


def test_audio_dubbing_schema_has_budget_fencing_translation_speech_and_final_evidence() -> None:
    import app.db.models  # noqa: F401

    columns = set(Base.metadata.tables["audio_dubbing_executions"].c.keys())
    assert {
        "status",
        "provider_state",
        "armed_at",
        "provider_submitted_at",
        "attempts",
        "max_attempts",
        "lease_token",
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "source_transcript_storage_key",
        "source_transcript_checksum",
        "voice_bindings",
        "estimated_translation_cost_usd",
        "max_translation_cost_usd",
        "speech_cost_upper_bound_usd",
        "max_total_cost_usd",
        "translation_storage_key",
        "translation_checksum",
        "speech_pipelines",
        "replacement_history",
        "final_graph_id",
        "final_output_checksum",
    } <= columns
