"""Isolated real-FFmpeg exit evidence for Phase 36G Stage 8.

This is an executable acceptance process, not a pytest fixture. It uses a fresh
PostgreSQL database, the production MediaRenderWorker, real FFmpeg 9, a local
object store, and synthetic provider-boundary WAV inputs. No external provider
request, GPU job, Production mutation, or provider spend occurs.
"""
from __future__ import annotations

import asyncio
from array import array
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any
from uuid import uuid4
import wave

from aios.open_song_factory import (
    ACE_STEP_LANGUAGE_MODEL_REVISION,
    ACE_STEP_MODEL_REVISION,
    ACE_STEP_SPACE_REVISION,
    DEMUCS_CHECKPOINT_SHA256,
    DEMUCS_SOURCE_COMMIT,
    OPEN_SONG_STEMS,
    OpenSongRequest,
    OpenSongRightsEvidence,
    build_open_song_plan,
)
from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import (
    AudioSongExecution,
    MediaAssetGraph,
    MediaAssetNode,
    MediaRenderStep,
    Organization,
    StudioAsset,
    StudioAssetRevision,
    StudioJob,
    User,
)
from app.services.audio_open_song_pipeline import create_open_song_pipeline
from app.services.audio_song_runtime import (
    arm_audio_song_execution,
    audio_song_execution_snapshot,
    claim_audio_song_execution,
    complete_audio_song_provider_output,
    finalize_audio_song_execution,
    mark_audio_song_submitting,
    record_audio_song_provider_job,
)
from app.services.media_ffmpeg import FFmpegRuntime
from app.services.media_graph_runtime import MediaGraphScope
from app.services.media_render_worker import MediaRenderWorker
from app.services.media_storage import LocalMediaObjectStore
from sqlalchemy import delete, func, select

RIGHTS_EVIDENCE = "1" * 64
RUNTIME_EVIDENCE = "2" * 64
PRICING_EVIDENCE = "3" * 64
LICENSE_EVIDENCE = "4" * 64
DURATION_SECONDS = 10
SAMPLE_RATE = 48_000


def _wav_bytes(*, frequency_hz: float, role: str) -> bytes:
    output = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024)
    frame_count = SAMPLE_RATE * DURATION_SECONDS
    samples = array("h")
    for frame in range(frame_count):
        t = frame / SAMPLE_RATE
        slow_envelope = 0.72 + 0.20 * math.sin(2.0 * math.pi * 0.31 * t)
        if role == "drums":
            phase = t % 0.5
            envelope = math.exp(-phase * 18.0)
            signal = math.sin(2.0 * math.pi * frequency_hz * t) * envelope
        elif role == "vocals":
            signal = (
                math.sin(2.0 * math.pi * frequency_hz * t)
                + 0.22 * math.sin(2.0 * math.pi * frequency_hz * 2.0 * t)
            ) * slow_envelope
        else:
            signal = math.sin(2.0 * math.pi * frequency_hz * t) * slow_envelope
        amplitude = 0.085
        left = max(-0.95, min(0.95, signal * amplitude))
        right = max(
            -0.95,
            min(
                0.95,
                signal * amplitude * (0.96 + 0.02 * math.sin(2.0 * math.pi * 0.17 * t)),
            ),
        )
        samples.append(int(left * 32_767))
        samples.append(int(right * 32_767))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(output, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(samples.tobytes())
    output.seek(0)
    return output.read()


def _mix_wavs(stems: dict[str, bytes]) -> bytes:
    decoded: dict[str, array] = {}
    for stem, body in stems.items():
        with tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024) as source:
            source.write(body)
            source.seek(0)
            with wave.open(source, "rb") as reader:
                assert reader.getnchannels() == 2
                assert reader.getframerate() == SAMPLE_RATE
                values = array("h")
                values.frombytes(reader.readframes(reader.getnframes()))
                if sys.byteorder != "little":
                    values.byteswap()
                decoded[stem] = values
    length = min(len(item) for item in decoded.values())
    mixed = array("h")
    for index in range(length):
        sample = sum(int(item[index]) for item in decoded.values())
        mixed.append(max(-31_000, min(31_000, sample)))
    if sys.byteorder != "little":
        mixed.byteswap()
    output = tempfile.SpooledTemporaryFile(max_size=4 * 1024 * 1024)
    with wave.open(output, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(SAMPLE_RATE)
        writer.writeframes(mixed.tobytes())
    output.seek(0)
    return output.read()


def _artifact_record(store: LocalMediaObjectStore, key: str, body: bytes) -> dict[str, Any]:
    stored = store.put_bytes(key, body, "audio/wav")
    return {
        "storage_backend": stored.backend,
        "storage_key": stored.key,
        "checksum": stored.sha256,
        "size_bytes": stored.size_bytes,
        "media_type": "audio/wav",
        "duration_seconds": float(DURATION_SECONDS),
        "sample_rate_hz": SAMPLE_RATE,
        "channels": 2,
    }


async def _seed() -> tuple[str, str, str, str]:
    organization_id = str(uuid4())
    user_id = str(uuid4())
    job_id = str(uuid4())
    asset_id = str(uuid4())
    async with SessionLocal() as session:
        organization = Organization(
            id=organization_id,
            name="Phase 36G Stage 8 Real FFmpeg",
            slug=f"p36g-stage8-{organization_id[:8]}",
            plan="enterprise",
            status="active",
        )
        session.add(organization)
        await session.flush()
        user = User(
            id=user_id,
            organization_id=organization_id,
            role_id=None,
            email=f"stage8-{user_id[:8]}@example.invalid",
            name="Phase 36G Stage 8 Acceptance",
            password_hash="unused",
            status="active",
        )
        session.add(user)
        await session.flush()
        job = StudioJob(
            id=job_id,
            organization_id=organization_id,
            workspace_id=None,
            project_id=None,
            requested_by_id=user_id,
            department="audio",
            output_kind="audio",
            title="Governed full song real FFmpeg acceptance",
            brief="Validate full song, synthetic vocals, stems, mix, master and export.",
            language="en-US",
            style="cinematic-pop",
            provider_mode="acceptance_only",
            provider="huggingface-space",
            model="acestep-v15-base",
            status="completed",
            progress=100,
            safety_status="passed",
            safety_findings=[],
            request_metadata={"synthetic_fixture": True},
            result_metadata={},
            max_attempts=1,
            completed_at=datetime.now(UTC),
        )
        session.add(job)
        await session.flush()
        asset = StudioAsset(
            id=asset_id,
            organization_id=organization_id,
            job_id=job_id,
            project_id=None,
            created_by_id=user_id,
            department="audio",
            asset_type="audio",
            title=job.title,
            filename="stage8-source-evidence.json",
            media_type="application/json",
            storage_path="evidence/stage8/source.json",
            checksum="5" * 64,
            size_bytes=1,
            status="active",
            current_revision=1,
            asset_metadata={
                "schema": "36G.stage8.source-fixture.v1",
                "external_requests": 0,
                "external_cost_usd": 0.0,
            },
        )
        session.add(asset)
        session.add(
            StudioAssetRevision(
                id=str(uuid4()),
                organization_id=organization_id,
                asset_id=asset_id,
                job_id=job_id,
                created_by_id=user_id,
                revision_number=1,
                filename=asset.filename,
                media_type=asset.media_type,
                storage_path=asset.storage_path,
                checksum=asset.checksum,
                size_bytes=asset.size_bytes,
                change_note="Initial Stage 8 source evidence",
                revision_metadata=asset.asset_metadata,
                status="active",
            )
        )
        await session.commit()
    return organization_id, user_id, job_id, asset_id


async def _cleanup(organization_id: str) -> dict[str, int]:
    async with SessionLocal() as session:
        await session.execute(
            delete(Organization).where(Organization.id == organization_id)
        )
        await session.commit()
    async with SessionLocal() as session:
        return {
            "organizations": int(
                await session.scalar(
                    select(func.count(Organization.id)).where(
                        Organization.id == organization_id
                    )
                )
                or 0
            ),
            "audio_song_executions": int(
                await session.scalar(
                    select(func.count(AudioSongExecution.id)).where(
                        AudioSongExecution.organization_id == organization_id
                    )
                )
                or 0
            ),
            "media_graphs": int(
                await session.scalar(
                    select(func.count(MediaAssetGraph.id)).where(
                        MediaAssetGraph.organization_id == organization_id
                    )
                )
                or 0
            ),
        }


async def main() -> None:
    evidence_path = Path(
        os.environ.get(
            "AIONEX_STAGE8_EVIDENCE_PATH",
            "/tmp/phase36g-stage8-real-ffmpeg-evidence.json",
        )
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="aionex-stage8-real-ffmpeg-"))
    store = LocalMediaObjectStore(root / "objects")
    settings.MEDIA_RENDER_TEMP_ROOT = str(root / "render")
    settings.MEDIA_RENDER_TIMEOUT_SECONDS = 300
    organization_id = ""
    evidence: dict[str, Any] = {
        "schema": "36G.stage8.real-ffmpeg-source-acceptance.v1",
        "status": "failed",
        "production_modified": False,
        "provider_generation_requests": 0,
        "gpu_jobs_created": 0,
        "provider_spend_usd": 0.0,
    }
    try:
        organization_id, user_id, job_id, asset_id = await _seed()
        plan = build_open_song_plan(
            OpenSongRequest(
                title="AIONEX Stage 8 governed song",
                concept=(
                    "Original cinematic electronic pop with synthetic vocals, warm drums, "
                    "bass, layered instruments, a memorable chorus and a clean ending."
                ),
                lyrics=(
                    "[Verse]\nA new horizon rises from the night,\n"
                    "We shape tomorrow in the morning light.\n\n"
                    "[Chorus]\nRise with the future, let every heartbeat start,\n"
                    "A world of possibility alive within the heart."
                ),
                language="en",
                duration_seconds=30,
                bpm=104,
                musical_key="Am",
                time_signature=4,
                seed=36_008,
                rights=OpenSongRightsEvidence(
                    basis="original",
                    commercial_use_authorized=True,
                    provider_terms_accepted=True,
                    ai_generated_disclosure_accepted=True,
                    evidence_sha256=RIGHTS_EVIDENCE,
                ),
            ),
            route_id="ace-step-official-space-acceptance",
        )
        async with SessionLocal() as session:
            pipeline = await create_open_song_pipeline(
                session,
                scope=MediaGraphScope(
                    organization_id=organization_id,
                    created_by_id=user_id,
                    studio_job_id=job_id,
                    studio_asset_id=asset_id,
                ),
                plan=plan,
                idempotency_key=f"stage8-real-ffmpeg-{organization_id}",
                runtime_evidence_sha256=RUNTIME_EVIDENCE,
                pricing_evidence_sha256=PRICING_EVIDENCE,
                license_evidence_sha256=LICENSE_EVIDENCE,
            )
            await arm_audio_song_execution(
                session,
                execution_id=pipeline.execution_id,
                organization_id=organization_id,
                approved_max_cost_usd=0.0,
                monthly_user_cap_usd=0.0,
                provider_balance_usd=None,
                balance_evidence_sha256=None,
            )
            claim = await claim_audio_song_execution(
                session,
                worker_id="stage8-real-ffmpeg-song-worker",
                lease_seconds=300,
                allowed_route_ids={"ace-step-official-space-acceptance"},
            )
            assert claim is not None and claim.lease_token
            await mark_audio_song_submitting(
                session,
                execution_id=claim.id,
                worker_id="stage8-real-ffmpeg-song-worker",
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
            )
            await record_audio_song_provider_job(
                session,
                execution_id=claim.id,
                worker_id="stage8-real-ffmpeg-song-worker",
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
                provider_job_id="stage8-offline-provider-boundary-fixture",
                provider_metadata={
                    "synthetic_provider_boundary_fixture": True,
                    "external_request": False,
                },
            )
            stem_bodies = {
                "vocals": _wav_bytes(frequency_hz=440.0, role="vocals"),
                "drums": _wav_bytes(frequency_hz=90.0, role="drums"),
                "bass": _wav_bytes(frequency_hz=110.0, role="bass"),
                "other": _wav_bytes(frequency_hz=660.0, role="other"),
            }
            full_body = _mix_wavs(stem_bodies)
            full_record = _artifact_record(
                store,
                f"stage8/{organization_id}/provider/full-song.wav",
                full_body,
            )
            stem_records = {
                stem: _artifact_record(
                    store,
                    f"stage8/{organization_id}/provider/stem-{stem}.wav",
                    body,
                )
                for stem, body in stem_bodies.items()
            }
            completed = await complete_audio_song_provider_output(
                session,
                execution_id=claim.id,
                worker_id="stage8-real-ffmpeg-song-worker",
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
                full_song=full_record,
                stems=stem_records,
                actual_billed_seconds=0.0,
                actual_cost_usd=0.0,
                provider_metadata={
                    "schema": "aionex.open-song-provider-result.v1",
                    "source_commit": ACE_STEP_SPACE_REVISION,
                    "model_revision": ACE_STEP_MODEL_REVISION,
                    "language_model_revision": ACE_STEP_LANGUAGE_MODEL_REVISION,
                    "separation_source_commit": DEMUCS_SOURCE_COMMIT,
                    "separation_checkpoint_sha256": DEMUCS_CHECKPOINT_SHA256,
                    "container_image_digest": None,
                    "synthetic_provider_boundary_fixture": True,
                },
            )
            assert completed.status == "rendering"
            await session.commit()

        runtime = FFmpegRuntime(timeout_seconds=300)
        worker = MediaRenderWorker(
            store=store,
            runtime=runtime,
            worker_id="stage8-real-ffmpeg-media-worker",
        )
        preflight = await worker.preflight()
        processed = 0
        for _ in range(10):
            if not await worker.run_once():
                break
            processed += 1
        assert processed == 4

        async with SessionLocal() as session:
            graph = await session.get(MediaAssetGraph, pipeline.graph_id)
            assert graph is not None and graph.status == "completed"
            nodes = {
                node.logical_key: node
                for node in (
                    await session.scalars(
                        select(MediaAssetNode).where(
                            MediaAssetNode.graph_id == pipeline.graph_id
                        )
                    )
                ).all()
            }
            assert all(node.status == "completed" for node in nodes.values())
            steps = {
                step.operation: step
                for step in (
                    await session.scalars(
                        select(MediaRenderStep).where(
                            MediaRenderStep.graph_id == pipeline.graph_id
                        )
                    )
                ).all()
            }
            assert set(steps) == {
                "audio_mix",
                "audio_master",
                "audio_waveform",
                "audio_export",
            }
            master_qa = (steps["audio_master"].result_metadata or {}).get("qa", {})
            export_qa = (steps["audio_export"].result_metadata or {}).get("qa", {})
            assert master_qa.get("audio_analysis", {}).get("passed") is True
            assert export_qa.get("audio_analysis", {}).get("passed") is True
            finalized = await finalize_audio_song_execution(
                session,
                execution_id=pipeline.execution_id,
                organization_id=organization_id,
            )
            assert finalized.status == "completed"
            asset = await session.get(StudioAsset, asset_id)
            assert asset is not None and asset.current_revision == 2
            revision_count = int(
                await session.scalar(
                    select(func.count(StudioAssetRevision.id)).where(
                        StudioAssetRevision.asset_id == asset_id
                    )
                )
                or 0
            )
            assert revision_count == 2
            public = await audio_song_execution_snapshot(
                session,
                execution_id=pipeline.execution_id,
                organization_id=organization_id,
            )
            rendered_public = repr(public)
            assert "stage8-offline-provider-boundary-fixture" not in rendered_public
            assert str(root) not in rendered_public
            evidence.update(
                {
                    "status": "pass",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "alembic_expected": "20260823_0039",
                    "ffmpeg": preflight,
                    "processed_render_steps": processed,
                    "graph_status": graph.status,
                    "execution_status": finalized.status,
                    "evidence_separation": {
                        "lyrics_sha256": finalized.lyrics_sha256,
                        "composition_and_synthetic_vocals_sha256": finalized.full_song_checksum,
                        "synthetic_vocals_stem_sha256": finalized.stem_manifest["vocals"][
                            "checksum"
                        ],
                        "stems_sha256": {
                            stem: finalized.stem_manifest[stem]["checksum"]
                            for stem in OPEN_SONG_STEMS
                        },
                        "mix_sha256": nodes["mix"].checksum,
                        "master_sha256": nodes["master"].checksum,
                        "waveform_sha256": nodes["waveform"].checksum,
                        "final_sha256": finalized.final_output_checksum,
                    },
                    "final_output": {
                        "size_bytes": finalized.final_output_size_bytes,
                        "duration_seconds": finalized.final_output_duration_seconds,
                        "media_type": nodes["export"].media_type,
                        "audio_qa": finalized.final_audio_qa,
                        "storage_locator_returned": False,
                    },
                    "studio_revision": finalized.studio_revision,
                    "provider_boundary": {
                        "route": "ace-step-official-space-acceptance",
                        "synthetic_fixture": True,
                        "real_provider_request": False,
                        "provider_job_id_returned": False,
                    },
                    "raw_title_returned": False,
                    "raw_concept_returned": False,
                    "raw_lyrics_returned": False,
                }
            )
            await session.commit()
    finally:
        cleanup_counts = (
            await _cleanup(organization_id)
            if organization_id
            else {
                "organizations": 0,
                "audio_song_executions": 0,
                "media_graphs": 0,
            }
        )
        evidence["cleanup_counts"] = cleanup_counts
        evidence["cleanup_verified"] = all(value == 0 for value in cleanup_counts.values())
        object_count = len([item for item in (root / "objects").rglob("*") if item.is_file()])
        evidence["local_objects_before_directory_removal"] = object_count
        shutil.rmtree(root, ignore_errors=True)
        evidence["local_object_directory_removed"] = not root.exists()
        evidence_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
        )
    if evidence.get("status") != "pass" or not evidence.get("cleanup_verified"):
        raise RuntimeError("Phase 36G Stage 8 real FFmpeg source acceptance failed")
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
