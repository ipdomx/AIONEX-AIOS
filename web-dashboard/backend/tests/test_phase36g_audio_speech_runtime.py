"""Phase 36G durable stock-voice speech + local media pipeline contracts."""
from __future__ import annotations

import hashlib
import io
import json
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from aios.audio_factory import AudioRequest, build_audio_plan
from app.core.config import settings
from app.db.base import Base, SessionLocal
from app.db.models import (
    AudioSpeechExecution,
    AuditEvent,
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    Organization,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    User,
)
from app.services.audio_speech_pipeline import (
    AudioSpeechPipelineError,
    build_stock_speech_graph_spec,
    create_stock_speech_pipeline,
)
from app.services.audio_speech_runtime import (
    AudioSpeechExecutionAuthority,
    AudioSpeechExecutionError,
    AudioSpeechLeaseLost,
    arm_audio_speech_execution,
    audio_speech_execution_snapshot,
)
from app.services.media_ffmpeg import MediaRenderResult, render_command_hash
from app.services.media_graph_runtime import MediaGraphScope, media_graph_snapshot
from app.services.media_render_worker import MediaRenderWorker
from app.services.media_storage import LocalMediaObjectStore
from sqlalchemy import delete, func, select


MODEL = "gpt-4o-mini-tts-2025-12-15"
TEXT = "Welcome to AIONEX, where intelligent projects come to life."
INSTRUCTIONS = "Speak clearly, warmly, and at a calm professional pace."


def wav_bytes(
    *,
    frames: int = 24_000,
    sample_rate: int = 24_000,
    channels: int = 1,
) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(b"\x00\x00" * frames * channels)
    return output.getvalue()


class FakeAudioRuntime:
    def preflight(self) -> dict[str, object]:
        return {
            "engine": "ffmpeg",
            "version": "9.0",
            "required_audio_filters": [
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
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if profile_id == "image-png-lossless":
            output_path.write_bytes(b"\x89PNG\r\n\x1a\n" + hashlib.sha256(payload).digest() * 8)
            streams = [
                {
                    "codec_type": "video",
                    "codec_name": "png",
                    "width": int(metadata.get("width", 1_200)),
                    "height": int(metadata.get("height", 320)),
                }
            ]
            format_data = {"format_name": "png_pipe"}
            qa: dict[str, object] = {
                "passed": True,
                "profile": profile_id,
                "operation": operation,
            }
        else:
            output_path.write_bytes(wav_bytes(frames=48_000, sample_rate=48_000, channels=2))
            streams = [
                {
                    "codec_type": "audio",
                    "codec_name": "pcm_s16le",
                    "sample_rate": "48000",
                    "channels": 2,
                }
            ]
            format_data = {"format_name": "wav", "duration": "1.000"}
            qa = {
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


class Scope:
    def __init__(
        self,
        org_id: str,
        user_id: str,
        job_id: str,
        asset_id: str,
    ) -> None:
        self.org_id = org_id
        self.user_id = user_id
        self.job_id = job_id
        self.asset_id = asset_id


async def seed_scope(tag: str) -> Scope:
    suffix = uuid4().hex[:12]
    async with SessionLocal() as session:
        org = Organization(
            id=f"p36g-speech-org-{suffix}",
            name=f"P36G Stock Speech {tag}",
            slug=f"p36g-speech-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(org)
        await session.flush()
        user = User(
            id=f"p36g-speech-user-{suffix}",
            organization_id=org.id,
            role_id=None,
            email=f"{tag}-{suffix}@phase36g.example.invalid",
            name="Phase36G Stock Speech User",
            password_hash="unused",
            status="active",
        )
        session.add(user)
        await session.flush()
        job = StudioJob(
            id=f"p36g-speech-job-{suffix}",
            organization_id=org.id,
            workspace_id=None,
            project_id=None,
            requested_by_id=user.id,
            department="audio",
            output_kind="audio",
            title="Phase 36G stock speech",
            brief="Create a bounded stock-voice narration and finish it locally.",
            language="en-US",
            style="professional",
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
            id=f"p36g-speech-asset-{suffix}",
            organization_id=org.id,
            job_id=job.id,
            project_id=None,
            created_by_id=user.id,
            department="audio",
            asset_type="audio",
            title=job.title,
            filename="phase36g-stock-speech-plan.zip",
            media_type="application/zip",
            storage_path="/tmp/phase36g-stock-speech-plan.zip",
            checksum="a" * 64,
            size_bytes=1,
            status="active",
            current_revision=1,
            asset_metadata={"render_status": "planned"},
        )
        session.add(asset)
        session.add(
            StudioAssetRevision(
                id=f"p36g-speech-revision-{suffix}",
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
        await session.commit()
        return Scope(org.id, user.id, job.id, asset.id)


async def cleanup_scope(scope: Scope) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id == scope.org_id))
        await session.commit()


def plan(**overrides):
    payload = {
        "title": "AIONEX bounded stock narration",
        "brief": "Create one concise governed stock-voice narration for acceptance.",
        "operation": "narration",
        "use_case": "advertisement",
        "language": "en-US",
        "purpose": "phase36g-stock-tts-acceptance",
        "script": TEXT,
        "speaker_count": 1,
        "voice_mode": "stock",
        "source_count": 0,
        "output_profile_id": "wav-pcm-48k-stereo",
        "include_music": False,
        "include_sfx": False,
    }
    payload.update(overrides)
    return build_audio_plan(AudioRequest(**payload))


async def create_pipeline(
    scope: Scope,
    *,
    key: str,
    max_attempts: int = 1,
):
    async with SessionLocal() as session:
        result = await create_stock_speech_pipeline(
            session,
            scope=MediaGraphScope(
                organization_id=scope.org_id,
                created_by_id=scope.user_id,
                studio_job_id=scope.job_id,
                studio_asset_id=scope.asset_id,
            ),
            plan=plan(),
            provider="openai",
            model=MODEL,
            voice="marin",
            instructions=INSTRUCTIONS,
            speed=1.0,
            max_duration_seconds=20.0,
            estimated_cost_usd=0.01,
            max_cost_usd=0.05,
            idempotency_key=key,
            max_attempts=max_attempts,
        )
        await session.commit()
        return result


async def drain(worker: MediaRenderWorker, limit: int = 20) -> int:
    processed = 0
    for _ in range(limit):
        if not await worker.run_once():
            break
        processed += 1
    return processed


def test_stock_speech_graph_is_deterministic_and_excludes_music_sfx_and_voice_clone() -> None:
    first = build_stock_speech_graph_spec(
        plan(),
        provider="openai",
        model=MODEL,
        voice="marin",
        instructions=INSTRUCTIONS,
        speed=1.0,
    )
    second = build_stock_speech_graph_spec(
        plan(),
        provider="openai",
        model=MODEL,
        voice="marin",
        instructions=INSTRUCTIONS,
        speed=1.0,
    )
    assert first.checksum == second.checksum
    assert first.topological_order == (
        "speech",
        "cleanup",
        "master",
        "waveform",
        "export",
    )
    assert [item.key for item in first.nodes] == [
        "speech",
        "cleanup",
        "master",
        "waveform",
        "export",
    ]
    provider = next(item for item in first.nodes if item.key == "speech")
    assert provider.parameters == {}
    assert provider.rights_metadata == {
        "voice_mode": "stock",
        "custom_voice": False,
        "voice_clone": False,
        "voice_transformation": False,
    }
    rendered = repr(first)
    assert TEXT not in rendered
    assert INSTRUCTIONS not in rendered
    assert "voice-clone" not in rendered
    assert "compose-music" not in rendered
    assert "generate-sfx" not in rendered


@pytest.mark.parametrize(
    "bad_plan",
    [
        plan(voice_mode="none"),
        plan(speaker_count=2),
        plan(include_music=True),
        plan(include_sfx=True),
        plan(operation="podcast", speaker_count=2),
    ],
)
def test_stock_speech_graph_rejects_unproven_scope(bad_plan) -> None:
    with pytest.raises(AudioSpeechPipelineError):
        build_stock_speech_graph_spec(
            bad_plan,
            provider="openai",
            model=MODEL,
            voice="marin",
            instructions=INSTRUCTIONS,
            speed=1.0,
        )


def test_audio_speech_schema_has_arm_fencing_ambiguity_cost_and_output_evidence() -> None:
    import app.db.models  # noqa: F401

    columns = set(Base.metadata.tables["audio_speech_executions"].c.keys())
    assert {
        "status",
        "provider_state",
        "armed_at",
        "lease_token",
        "lease_owner",
        "lease_expires_at",
        "fencing_token",
        "provider_request_id",
        "provider_submitted_at",
        "attempts",
        "max_attempts",
        "input_sha256",
        "instructions_sha256",
        "input_characters",
        "estimated_cost_usd",
        "max_cost_usd",
        "actual_cost_usd",
        "cost_basis",
        "output_storage_key",
        "output_checksum",
        "output_duration_seconds",
        "usage_metadata",
        "provider_response_metadata",
    } <= columns


@pytest.mark.asyncio
async def test_pipeline_is_idempotent_planned_and_requires_exact_owner_cost_arm(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("arm")
    authority = AudioSpeechExecutionAuthority(
        store=LocalMediaObjectStore(tmp_path / "objects"),
        worker_id="speech-worker-a",
    )
    try:
        first = await create_pipeline(scope, key="phase36g-stock-speech-arm")
        same = await create_pipeline(scope, key="phase36g-stock-speech-arm")
        assert same.graph_id == first.graph_id
        assert same.speech_execution_id == first.speech_execution_id
        assert await authority.claim() is None
        async with SessionLocal() as session:
            steps = list(
                (
                    await session.scalars(
                        select(MediaRenderStep).where(
                            MediaRenderStep.graph_id == first.graph_id
                        )
                    )
                ).all()
            )
            assert {item.operation for item in steps} == {
                "audio_cleanup",
                "audio_master",
                "audio_waveform",
                "audio_export",
            }
            assert len(steps) == 4
            with pytest.raises(AudioSpeechExecutionError, match="cost approval"):
                await arm_audio_speech_execution(
                    session,
                    execution_id=first.speech_execution_id,
                    organization_id=scope.org_id,
                    approved_max_cost_usd=0.04,
                )
            row = await arm_audio_speech_execution(
                session,
                execution_id=first.speech_execution_id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.05,
            )
            assert row.status == "queued" and row.provider_state == "not_started"
            assert row.armed_at is not None
            await session.commit()
        claim = await authority.claim()
        assert claim is not None
        assert claim.execution_id == first.speech_execution_id
        assert claim.fencing_token == 1
        snapshot = first.public_snapshot()
        assert snapshot["provider_requests"] == 0
        assert snapshot["provider_spend_usd"] == 0.0
        assert TEXT not in repr(snapshot)
        assert INSTRUCTIONS not in repr(snapshot)
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_provider_wav_completes_then_local_worker_finishes_studio_revision_without_leaks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = await seed_scope("complete")
    store = LocalMediaObjectStore(tmp_path / "objects")
    authority = AudioSpeechExecutionAuthority(store=store, worker_id="speech-worker-a")
    monkeypatch.setattr(settings, "MEDIA_RENDER_TEMP_ROOT", str(tmp_path / "render"))
    media_worker = MediaRenderWorker(
        store=store,
        runtime=FakeAudioRuntime(),  # type: ignore[arg-type]
        worker_id="media-worker-a",
    )
    try:
        created = await create_pipeline(scope, key="phase36g-stock-speech-complete")
        async with SessionLocal() as session:
            await arm_audio_speech_execution(
                session,
                execution_id=created.speech_execution_id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.05,
            )
            await session.commit()
        claim = await authority.claim()
        assert claim is not None
        await authority.mark_submission_started(claim)
        provider_body = wav_bytes()
        result = await authority.complete_bytes(
            claim,
            body=provider_body,
            content_type="audio/wav",
            provider_request_id="req-sensitive-provider-id",
            provider_response_metadata={
                "duration_seconds": 1.0,
                "sample_rate_hz": 24_000,
                "channels": 1,
                "input_text": TEXT,
                "authorization": "must-not-persist",
            },
            usage_metadata={
                "provider_usage_reported": False,
                "input_characters": len(TEXT),
                "api_key": "must-not-persist",
                "cost_basis": "official_rate_cap",
            },
            actual_cost_usd=None,
            cost_basis="official_rate_cap",
        )
        assert result["status"] == "completed"
        async with SessionLocal() as session:
            execution = await session.get(
                AudioSpeechExecution, created.speech_execution_id
            )
            graph = await session.get(MediaAssetGraph, created.graph_id)
            speech = await session.get(MediaAssetNode, created.speech_node_id)
            assert execution is not None and execution.provider_state == "completed"
            assert execution.actual_cost_usd is None
            assert execution.cost_basis == "official_rate_cap"
            assert "input_text" not in execution.provider_response_metadata
            assert "authorization" not in execution.provider_response_metadata
            assert "api_key" not in execution.usage_metadata
            assert speech is not None and speech.status == "completed"
            assert speech.storage_key and speech.checksum
            assert graph is not None and graph.status == "rendering"
            public_execution = await audio_speech_execution_snapshot(
                session,
                execution_id=created.speech_execution_id,
                organization_id=scope.org_id,
            )
            public_graph = await media_graph_snapshot(session, graph)
            rendered = repr({"execution": public_execution, "graph": public_graph})
            assert TEXT not in rendered
            assert INSTRUCTIONS not in rendered
            assert "req-sensitive-provider-id" not in rendered
            assert "must-not-persist" not in rendered
            assert speech.storage_key not in rendered
        assert await drain(media_worker) == 4
        async with SessionLocal() as session:
            graph = await session.get(MediaAssetGraph, created.graph_id)
            asset = await session.get(StudioAsset, scope.asset_id)
            execution = await session.get(
                AudioSpeechExecution, created.speech_execution_id
            )
            nodes = {
                row.logical_key: row
                for row in (
                    await session.scalars(
                        select(MediaAssetNode).where(
                            MediaAssetNode.graph_id == created.graph_id
                        )
                    )
                ).all()
            }
            revision_count = int(
                await session.scalar(
                    select(func.count(StudioAssetRevision.id)).where(
                        StudioAssetRevision.asset_id == scope.asset_id
                    )
                )
                or 0
            )
            audit_count = int(
                await session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.resource_type == "audio_speech_execution",
                        AuditEvent.resource_id == created.speech_execution_id,
                        AuditEvent.action == "audio.speech.completed",
                    )
                )
                or 0
            )
            assert graph is not None and graph.status == "completed"
            assert asset is not None and asset.current_revision == 2
            assert asset.media_type == "audio/wav"
            assert revision_count == 2
            assert all(item.status == "completed" for item in nodes.values())
            assert nodes["waveform"].media_type == "image/png"
            assert nodes["export"].media_type == "audio/wav"
            assert execution is not None and execution.attempts == 1
            assert audit_count == 1
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_expired_submitting_lease_fails_ambiguous_without_second_claim(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("ambiguous")
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker_a = AudioSpeechExecutionAuthority(
        store=store,
        worker_id="speech-worker-a",
        lease_seconds=30,
    )
    worker_b = AudioSpeechExecutionAuthority(
        store=store,
        worker_id="speech-worker-b",
        lease_seconds=30,
    )
    try:
        created = await create_pipeline(
            scope,
            key="phase36g-stock-speech-ambiguous",
            max_attempts=1,
        )
        async with SessionLocal() as session:
            await arm_audio_speech_execution(
                session,
                execution_id=created.speech_execution_id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.05,
            )
            await session.commit()
        claim = await worker_a.claim()
        assert claim is not None
        await worker_a.mark_submission_started(claim)
        async with SessionLocal() as session:
            row = await session.get(
                AudioSpeechExecution, created.speech_execution_id
            )
            assert row is not None and row.provider_state == "submitting"
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        assert await worker_b.claim() is None
        async with SessionLocal() as session:
            row = await session.get(
                AudioSpeechExecution, created.speech_execution_id
            )
            graph = await session.get(MediaAssetGraph, created.graph_id)
            speech = await session.get(MediaAssetNode, created.speech_node_id)
            assert row is not None
            assert row.status == "failed" and row.provider_state == "ambiguous"
            assert row.attempts == row.max_attempts == 1
            assert row.error_code == "speech_submission_ambiguous"
            assert graph is not None and graph.status == "failed"
            assert speech is not None and speech.status == "failed"
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_pre_submission_expired_lease_is_fenced_and_reclaimed_with_budget(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("fencing")
    store = LocalMediaObjectStore(tmp_path / "objects")
    worker_a = AudioSpeechExecutionAuthority(
        store=store,
        worker_id="speech-worker-a",
        lease_seconds=30,
    )
    worker_b = AudioSpeechExecutionAuthority(
        store=store,
        worker_id="speech-worker-b",
        lease_seconds=30,
    )
    try:
        created = await create_pipeline(
            scope,
            key="phase36g-stock-speech-fencing",
            max_attempts=2,
        )
        async with SessionLocal() as session:
            await arm_audio_speech_execution(
                session,
                execution_id=created.speech_execution_id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.05,
            )
            await session.commit()
        first = await worker_a.claim()
        assert first is not None and first.fencing_token == 1
        async with SessionLocal() as session:
            row = await session.get(
                AudioSpeechExecution, created.speech_execution_id
            )
            assert row is not None and row.provider_state == "not_started"
            row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        second = await worker_b.claim()
        assert second is not None and second.fencing_token == 2
        with pytest.raises(AudioSpeechLeaseLost):
            await worker_a.renew(first)
        async with SessionLocal() as session:
            row = await session.get(
                AudioSpeechExecution, created.speech_execution_id
            )
            assert row is not None
            assert row.attempts == 2 and row.provider_state == "not_started"
            assert row.lease_owner == "speech-worker-b"
    finally:
        await cleanup_scope(scope)


@pytest.mark.asyncio
async def test_actual_cost_above_approved_cap_is_rejected_before_storage(
    tmp_path: Path,
) -> None:
    scope = await seed_scope("cost-cap")
    store = LocalMediaObjectStore(tmp_path / "objects")
    authority = AudioSpeechExecutionAuthority(store=store, worker_id="speech-worker-a")
    try:
        created = await create_pipeline(scope, key="phase36g-stock-speech-cost-cap")
        async with SessionLocal() as session:
            await arm_audio_speech_execution(
                session,
                execution_id=created.speech_execution_id,
                organization_id=scope.org_id,
                approved_max_cost_usd=0.05,
            )
            await session.commit()
        claim = await authority.claim()
        assert claim is not None
        await authority.mark_submission_started(claim)
        with pytest.raises(AudioSpeechExecutionError, match="approved cap"):
            await authority.complete_bytes(
                claim,
                body=wav_bytes(),
                content_type="audio/wav",
                provider_request_id="req-over-cap",
                provider_response_metadata={"duration_seconds": 1.0},
                usage_metadata={},
                actual_cost_usd=0.051,
                cost_basis="official_provider_usage",
            )
        assert not any(
            item.is_file()
            for item in (tmp_path / "objects").rglob("*")
            if item.name != ".media-storage-preflight"
        )
        async with SessionLocal() as session:
            row = await session.get(
                AudioSpeechExecution, created.speech_execution_id
            )
            assert row is not None and row.status == "running"
            assert row.provider_state == "submitting"
            assert row.output_storage_key is None
    finally:
        await cleanup_scope(scope)
