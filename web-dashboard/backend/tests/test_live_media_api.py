"""User-facing wiring tests for the governed Phase 36 live-media API.

These tests stop at the durable arm boundary.  No provider adapter is invoked and
no external spend is permitted.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api.v1.endpoints import live_media
from app.api.v1.router import api_router
from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    AudioMusicExecution,
    AudioSongExecution,
    AudioSpeechExecution,
    DesignImageExecution,
    MediaAssetGraph,
    MediaAssetNode,
    Organization,
    User,
    VideoExecution,
)
from app.services.free_tier import require_non_free_user
from aios.open_song_factory import OpenSongRuntimeBinding


async def _actor(tag: str) -> tuple[Organization, User, UserRecord]:
    suffix = uuid4().hex[:12]
    async with SessionLocal() as session:
        org = Organization(
            id=f"live-media-org-{suffix}",
            name=f"Live Media {tag}",
            slug=f"live-media-{tag}-{suffix}",
            plan="enterprise",
            status="active",
        )
        session.add(org)
        await session.flush()
        user = User(
            id=f"live-media-user-{suffix}",
            organization_id=org.id,
            role_id=None,
            email=f"{tag}-{suffix}@live-media.example.invalid",
            name="Live Media Test User",
            password_hash="unused",
            status="active",
        )
        session.add(user)
        await session.commit()
    actor = UserRecord(
        id=user.id,
        email=user.email,
        name=user.name,
        role="Owner",
        password_hash=user.password_hash,
        organization_id=org.id,
        organization_name=org.name,
        organization_plan=org.plan,
        permissions=["*"],
    )
    return org, user, actor


async def _cleanup(org_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(delete(Organization).where(Organization.id == org_id))
        await session.commit()


def _app(actor: UserRecord) -> FastAPI:
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_non_free_user] = lambda: actor
    return app


async def _inventory(_session, _actor, provider_type: str):
    assert provider_type == "openai"
    return None, (
        "gpt-image-2",
        "sora-2",
        "gpt-4o-mini-tts-2025-12-15",
        "gpt-4o-mini-transcribe-2025-12-15",
        "gpt-4o-transcribe-diarize",
        "gpt-5.6-luna",
    ), "phase36-live-media-test-evidence"


@pytest.mark.asyncio
async def test_live_image_http_wires_to_durable_armed_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    org, _user, actor = await _actor("image")
    monkeypatch.setattr(live_media, "_provider_inventory", _inventory)
    try:
        async with AsyncClient(transport=ASGITransport(app=_app(actor)), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/studio/live-media/image",
                json={
                    "title": "Governed social image",
                    "brief": "Create an original modern social visual for a product launch.",
                    "use_case": "social-post",
                    "preset_id": "social-square",
                    "operation": "generate",
                    "style": "modern",
                    "language": "en-US",
                    "output_format": "png",
                    "reference_node_ids": [],
                    "approved_max_cost_usd": 0.25,
                    "idempotency_key": f"live-image-{uuid4().hex}",
                },
            )
            jobs_response = await client.get("/api/v1/studio/live-media/jobs")
        assert response.status_code == 202, response.text
        assert jobs_response.status_code == 200, jobs_response.text
        body = response.json()
        jobs = jobs_response.json()["jobs"]
        assert any(item["kind"] == "image" and item["id"] == body["execution_id"] for item in jobs)
        assert jobs_response.json()["credential_returned"] is False
        assert jobs_response.json()["raw_provider_job_id_returned"] is False
        assert body["status"] == "queued"
        assert body["provider"] == "openai"
        assert body["model"] == "gpt-image-2"
        assert body["automatic_retry"] is False
        async with SessionLocal() as session:
            row = await session.get(DesignImageExecution, body["execution_id"])
            assert row is not None
            assert row.status == "queued"
            assert row.attempts == 0
            assert row.max_attempts == 1
            assert row.actual_cost_usd is None
            assert row.request_options["approval_mode"] == "explicit-user-cap"
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_live_video_http_arms_only_with_total_cost_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    org, _user, actor = await _actor("video")
    monkeypatch.setattr(live_media, "_provider_inventory", _inventory)
    try:
        async with AsyncClient(transport=ASGITransport(app=_app(actor)), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/studio/live-media/video",
                json={
                    "title": "Governed launch video",
                    "brief": "Create a short four-scene original launch advertisement with no references.",
                    "operation": "text-to-video",
                    "use_case": "advertisement",
                    "aspect_ratio": "16:9",
                    "resolution": "720p",
                    "language": "en-US",
                    "style": "cinematic",
                    "approved_max_total_cost_usd": 3.0,
                    "idempotency_key": f"live-video-{uuid4().hex}",
                },
            )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["provider"] == "openai"
        assert body["model"] == "sora-2"
        assert body["projected_cost_usd"] <= 3.0
        assert body["automatic_retry"] is False
        async with SessionLocal() as session:
            rows = list((await session.scalars(select(VideoExecution).where(VideoExecution.graph_id == body["graph_id"]))).all())
            assert rows
            assert all(row.status == "queued" for row in rows)
            assert all(row.attempts == 0 for row in rows)
            assert all(row.provider_job_id is None for row in rows)
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_live_speech_http_stops_at_one_attempt_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    org, _user, actor = await _actor("speech")
    monkeypatch.setattr(live_media, "_provider_inventory", _inventory)
    try:
        async with AsyncClient(transport=ASGITransport(app=_app(actor)), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/studio/live-media/speech",
                json={
                    "title": "Governed narration",
                    "text": "This is an original short narration for the AIONEX live media contract test.",
                    "language": "en-US",
                    "voice": "marin",
                    "approved_max_cost_usd": 0.05,
                    "idempotency_key": f"live-speech-{uuid4().hex}",
                },
            )
        assert response.status_code == 202, response.text
        body = response.json()
        execution_id = body["id"] if "id" in body else body["execution_id"]
        async with SessionLocal() as session:
            row = await session.get(AudioSpeechExecution, execution_id)
            assert row is not None
            assert row.status == "queued"
            assert row.attempts == 0
            assert row.max_attempts == 1
            assert row.provider_request_id is None
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_live_replicate_music_uses_fixed_price_and_stops_before_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    org, _user, actor = await _actor("music-replicate")

    async def replicate_ready() -> str:
        return "a" * 64

    monkeypatch.setattr(live_media, "_replicate_preflight", replicate_ready)
    try:
        async with AsyncClient(transport=ASGITransport(app=_app(actor)), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/studio/live-media/music",
                json={
                    "title": "Original instrumental draft",
                    "prompt": "Original cinematic electronic instrumental with a resolved ending.",
                    "language": "en",
                    "provider": "replicate",
                    "tier": "draft",
                    "instrumental_only": True,
                    "lyrics": "",
                    "rights_basis": "instrumental",
                    "commercial_use_authorized": True,
                    "provider_terms_accepted": True,
                    "ai_generated_disclosure_accepted": True,
                    "approved_max_cost_usd": 0.04,
                    "idempotency_key": f"live-music-{uuid4().hex}",
                },
            )
        assert response.status_code == 202, response.text
        async with SessionLocal() as session:
            rows = list((await session.scalars(select(AudioMusicExecution).where(AudioMusicExecution.organization_id == org.id))).all())
            assert len(rows) == 1
            row = rows[0]
            assert row.status == "queued"
            assert row.attempts == 0
            assert row.provider_request_id is None
            assert float(row.max_cost_usd) == 0.04
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_live_stability_music_requires_exact_twenty_cent_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    org, _user, actor = await _actor("music-stability")

    async def stability_ready() -> str:
        return "b" * 64

    monkeypatch.setattr(live_media, "_stability_preflight", stability_ready)
    try:
        async with AsyncClient(transport=ASGITransport(app=_app(actor)), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/studio/live-media/music",
                json={
                    "title": "Original stable instrumental",
                    "prompt": "Original ambient instrumental bed with no vocals and a clean ending.",
                    "language": "en",
                    "provider": "stability",
                    "tier": "draft",
                    "instrumental_only": True,
                    "lyrics": "",
                    "rights_basis": "instrumental",
                    "commercial_use_authorized": True,
                    "provider_terms_accepted": True,
                    "ai_generated_disclosure_accepted": True,
                    "approved_max_cost_usd": 0.20,
                    "idempotency_key": f"live-stable-{uuid4().hex}",
                },
            )
        assert response.status_code == 202, response.text
        async with SessionLocal() as session:
            row = await session.scalar(select(AudioMusicExecution).where(AudioMusicExecution.organization_id == org.id))
            assert row is not None
            assert row.status == "queued"
            assert row.attempts == 0
            assert row.provider_request_id is None
            assert row.provider == "stability"
            assert float(row.max_cost_usd) == 0.20
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_live_open_song_records_approval_but_secret_worker_must_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    org, _user, actor = await _actor("song")
    binding = OpenSongRuntimeBinding(
        route_id="runpod-flex-a40",
        endpoint_id_sha256="1" * 64,
        container_image_repository="ipdomx/aionex-open-song",
        container_image_index_digest="sha256:" + "2" * 64,
        container_image_digest="sha256:" + "2" * 64,
        image_sbom_sha256="3" * 64,
        handler_source_sha256="4" * 64,
    )
    monkeypatch.setattr(
        live_media,
        "_open_song_binding_and_evidence",
        lambda: (binding, {"runtime": "5" * 64, "pricing": "6" * 64, "license": "7" * 64}),
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=_app(actor)), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/studio/live-media/song",
                json={
                    "title": "Original governed song",
                    "concept": "Original cinematic electronic pop with synthetic vocals and a clean resolved ending.",
                    "lyrics": "[Verse]\nWe make a new horizon in the morning light.\n[Chorus]\nOriginal voices carry through the night.",
                    "language": "en",
                    "duration_seconds": 30,
                    "bpm": 104,
                    "musical_key": "Am",
                    "rights_basis": "original",
                    "rights_evidence_sha256": "8" * 64,
                    "commercial_use_authorized": True,
                    "provider_terms_accepted": True,
                    "ai_generated_disclosure_accepted": True,
                    "approved_max_cost_usd": 0.20,
                    "monthly_user_cap_usd": 0.40,
                    "idempotency_key": f"live-song-{uuid4().hex}",
                },
            )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["arming_state"] == "awaiting-secret-worker-balance-check"
        assert body["endpoint_id_returned"] is False
        assert "runpod" not in response.text.lower() or "provider" in body
        async with SessionLocal() as session:
            row = await session.scalar(select(AudioSongExecution).where(AudioSongExecution.organization_id == org.id))
            assert row is not None
            assert row.status == "planned"
            assert row.attempts == 0
            assert row.provider_job_id is None
            assert row.provider_metadata["user_cost_approved"] is True
            assert row.provider_metadata["balance_check_delegated_to_secret_worker"] is True
    finally:
        await _cleanup(org.id)


@pytest.mark.asyncio
async def test_live_transcript_wires_owned_completed_wav_to_armed_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    org, user, actor = await _actor("transcript")
    monkeypatch.setattr(live_media, "_provider_inventory", _inventory)
    suffix = uuid4().hex
    async with SessionLocal() as session:
        graph = MediaAssetGraph(
            organization_id=org.id,
            workspace_id=None,
            project_id=None,
            studio_job_id=None,
            studio_asset_id=None,
            created_by_id=user.id,
            title="Live media transcript source",
            asset_kind="audio",
            output_profile="audio-wav-pcm",
            status="completed",
            graph_version=1,
            idempotency_key=f"live-transcript-source-{suffix}",
            graph_checksum="a" * 64,
            graph_metadata={},
            rights_metadata={},
            provenance=[{"type": "live-media-test"}],
        )
        session.add(graph)
        await session.flush()
        node = MediaAssetNode(
            graph_id=graph.id,
            organization_id=org.id,
            created_by_id=user.id,
            logical_key="source-audio",
            revision=1,
            node_type="audio-source",
            media_type="audio/wav",
            status="completed",
            storage_backend="local",
            storage_key=f"test/{suffix}.wav",
            checksum="b" * 64,
            size_bytes=1000,
            idempotency_key=f"live-transcript-node-{suffix}",
            source_metadata={"duration_ms": 5000, "sample_rate_hz": 48000, "channels": 1},
            prompt_metadata={},
            rights_metadata={},
            provenance=[{"type": "live-media-test"}],
            scene_metadata={},
            timeline_metadata={"duration_ms": 5000},
            operation_metadata={},
        )
        session.add(node)
        await session.commit()
        source_node_id = node.id
    try:
        async with AsyncClient(transport=ASGITransport(app=_app(actor)), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/studio/live-media/transcript",
                json={
                    "source_node_id": source_node_id,
                    "language": "en",
                    "operation": "transcribe",
                    "source_duration_ms": 5000,
                    "source_sample_rate_hz": 48000,
                    "source_channels": 1,
                    "approved_max_cost_usd": 0.01,
                    "idempotency_key": f"live-transcript-{uuid4().hex}",
                },
            )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["status"] == "queued"
        assert body["attempts"] == 0
        assert body["max_attempts"] == 1
    finally:
        await _cleanup(org.id)
