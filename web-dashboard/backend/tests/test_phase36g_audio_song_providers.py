"""No-network contracts for the Phase 36G Stage 8 RunPod transport."""
from __future__ import annotations

import hashlib
import json

import httpx
import pytest
from aios.open_song_factory import (
    ACE_STEP_IMAGE_AMD64_DIGEST,
    ACE_STEP_LANGUAGE_MODEL,
    ACE_STEP_LANGUAGE_MODEL_REVISION,
    ACE_STEP_MODEL_REVISION,
    ACE_STEP_SOURCE_COMMIT,
    DEMUCS_CHECKPOINT_SHA256,
    DEMUCS_MODEL,
    DEMUCS_SOURCE_COMMIT,
)

from app.services.audio_song_providers import (
    AudioSongProviderFailure,
    ProviderAudioArtifact,
    ProviderOpenSongRequest,
    RunPodOpenSongAdapter,
)

ENDPOINT_ID = "stage8_endpoint_01"
CREDENTIAL = "runpod-stage8-test-credential"
ARTIFACT_HOST = "assets.example.test"


def request() -> ProviderOpenSongRequest:
    return ProviderOpenSongRequest(
        route_id="runpod-flex-a40",
        model="acestep-v15-base",
        model_revision=ACE_STEP_MODEL_REVISION,
        language_model=ACE_STEP_LANGUAGE_MODEL,
        language_model_revision=ACE_STEP_LANGUAGE_MODEL_REVISION,
        source_commit=ACE_STEP_SOURCE_COMMIT,
        container_image_digest="sha256:" + "8" * 64,
        separation_model=DEMUCS_MODEL,
        separation_source_commit=DEMUCS_SOURCE_COMMIT,
        separation_checkpoint_sha256=DEMUCS_CHECKPOINT_SHA256,
        title="Original governed song",
        concept=(
            "Original cinematic pop with warm drums, clear synthetic vocals, "
            "and a resolved ending."
        ),
        lyrics=(
            "[Verse]\nWe build the morning from a quiet spark.\n"
            "[Chorus]\nRise with the light and make a hopeful mark."
        ),
        language="en",
        duration_seconds=30,
        bpm=104,
        musical_key="Am",
        time_signature=4,
        seed=36008,
    )


def artifact_payload(name: str, body: bytes) -> dict[str, object]:
    return {
        "url": f"https://{ARTIFACT_HOST}/{name}.wav",
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
        "media_type": "audio/wav",
        "duration_seconds": 30.0,
        "sample_rate_hz": 48_000,
        "channels": 2,
    }


def completed_payload(job_id: str, body: bytes) -> dict[str, object]:
    return {
        "id": job_id,
        "status": "COMPLETED",
        "executionTime": 99_001,
        "output": {
            "schema": "aionex.open-song-provider-result.v1",
            "source_commit": ACE_STEP_SOURCE_COMMIT,
            "model_revision": ACE_STEP_MODEL_REVISION,
            "language_model_revision": ACE_STEP_LANGUAGE_MODEL_REVISION,
            "container_image_digest": "sha256:" + "8" * 64,
            "separation_source_commit": DEMUCS_SOURCE_COMMIT,
            "separation_checkpoint_sha256": DEMUCS_CHECKPOINT_SHA256,
            "full_song": artifact_payload("song", body),
            "stems": {
                stem: artifact_payload(f"stem-{stem}", body)
                for stem in ("vocals", "drums", "bass", "other")
            },
        },
    }


def adapter(handler) -> RunPodOpenSongAdapter:
    return RunPodOpenSongAdapter(
        transport=httpx.MockTransport(handler),
        allowed_artifact_hosts={ARTIFACT_HOST},
    )


@pytest.mark.asyncio
async def test_submit_is_one_exact_runpod_request_and_returns_durable_job() -> None:
    calls: list[httpx.Request] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        calls.append(http_request)
        return httpx.Response(
            200,
            json={"id": "stage8-job-1", "status": "IN_QUEUE", "delayTime": 3},
        )

    job = await adapter(handler).submit(
        request(), credential=CREDENTIAL, endpoint_id=ENDPOINT_ID
    )
    assert job.job_id == "stage8-job-1"
    assert job.state == "IN_QUEUE"
    assert len(calls) == 1
    sent = calls[0]
    assert sent.method == "POST"
    assert sent.url.path == f"/v2/{ENDPOINT_ID}/run"
    payload = json.loads(sent.content)
    assert payload["input"]["schema"] == "aionex.open-song-request.v1"
    assert payload["input"]["song"]["lyrics"] == request().lyrics
    assert payload["input"]["safety"]["max_attempts"] == 1
    assert payload["input"]["safety"]["automatic_retry"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status", (429, 500, 503))
async def test_submit_uncertainty_is_ambiguous_and_never_retryable(status: int) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"type": "temporary"}})

    with pytest.raises(AudioSongProviderFailure) as raised:
        await adapter(handler).submit(
            request(), credential=CREDENTIAL, endpoint_id=ENDPOINT_ID
        )
    assert raised.value.ambiguous_submission is True
    assert raised.value.retryable is False


@pytest.mark.asyncio
async def test_poll_completed_result_is_supply_chain_and_cost_time_bounded() -> None:
    body = b"governed-audio" * 100

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == f"/v2/{ENDPOINT_ID}/status/stage8-job-2"
        return httpx.Response(200, json=completed_payload("stage8-job-2", body))

    job = await adapter(handler).retrieve(
        "stage8-job-2", credential=CREDENTIAL, endpoint_id=ENDPOINT_ID
    )
    assert job.state == "COMPLETED"
    assert job.billed_seconds == 100.0
    assert job.result is not None
    assert set(job.result.stems) == {"vocals", "drums", "bass", "other"}
    evidence = job.result.evidence_snapshot()
    assert evidence["source_commit"] == ACE_STEP_SOURCE_COMMIT
    assert evidence["raw_title_returned"] is False
    assert evidence["raw_lyrics_returned"] is False


@pytest.mark.asyncio
async def test_poll_rejects_changed_provider_job_identity() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "different-job", "status": "IN_QUEUE"})

    with pytest.raises(AudioSongProviderFailure, match="provider") as raised:
        await adapter(handler).retrieve(
            "stage8-job-3", credential=CREDENTIAL, endpoint_id=ENDPOINT_ID
        )
    assert raised.value.code == "provider_job_identity"
    assert raised.value.retryable is False


@pytest.mark.asyncio
async def test_poll_transport_failure_is_retryable_only_after_durable_job() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    with pytest.raises(AudioSongProviderFailure) as raised:
        await adapter(handler).retrieve(
            "stage8-job-4", credential=CREDENTIAL, endpoint_id=ENDPOINT_ID
        )
    assert raised.value.code == "provider_poll_transport"
    assert raised.value.retryable is True
    assert raised.value.ambiguous_submission is False


@pytest.mark.asyncio
async def test_download_is_host_size_and_checksum_bounded() -> None:
    body = b"RIFF" + b"stage8-audio" * 64
    declared = ProviderAudioArtifact(**artifact_payload("song", body))

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.host == ARTIFACT_HOST
        return httpx.Response(
            200,
            content=body,
            headers={
                "content-type": "audio/wav",
                "content-length": str(len(body)),
            },
        )

    downloaded = await adapter(handler).download(declared)
    assert downloaded.body == body
    assert downloaded.sha256 == hashlib.sha256(body).hexdigest()


@pytest.mark.asyncio
async def test_download_rejects_unapproved_host_before_network() -> None:
    body = b"x" * 128
    declared = ProviderAudioArtifact(
        url="https://unapproved.example.test/song.wav",
        sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
        media_type="audio/wav",
        duration_seconds=30.0,
        sample_rate_hz=48_000,
        channels=2,
    )
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=body)

    with pytest.raises(AudioSongProviderFailure) as raised:
        await adapter(handler).download(declared)
    assert raised.value.code == "provider_artifact_host"
    assert calls == 0


@pytest.mark.asyncio
async def test_download_rejects_content_checksum_or_length_drift() -> None:
    expected = b"a" * 128
    actual = b"b" * 128
    declared = ProviderAudioArtifact(**artifact_payload("song", expected))

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=actual,
            headers={
                "content-type": "audio/wav",
                "content-length": str(len(actual)),
            },
        )

    with pytest.raises(AudioSongProviderFailure) as raised:
        await adapter(handler).download(declared)
    assert raised.value.code == "provider_content_checksum"


def test_request_rejects_wrong_route_or_unpinned_image() -> None:
    values = request().__dict__ if hasattr(request(), "__dict__") else {
        field: getattr(request(), field)
        for field in request().__dataclass_fields__
    }
    values["route_id"] = "other-route"
    with pytest.raises(AudioSongProviderFailure) as route_error:
        ProviderOpenSongRequest(**values)
    assert route_error.value.code == "provider_route_unsupported"

    values = {
        field: getattr(request(), field)
        for field in request().__dataclass_fields__
    }
    values["container_image_digest"] = ACE_STEP_IMAGE_AMD64_DIGEST[:-1] + "z"
    with pytest.raises(AudioSongProviderFailure) as image_error:
        ProviderOpenSongRequest(**values)
    assert image_error.value.code == "provider_input_invalid"


@pytest.mark.asyncio
async def test_bridge_submission_download_and_cleanup_keep_tokens_ephemeral() -> None:
    bridge_host = "api.vip-e.net"
    bridge_secret = "phase36g-provider-bridge-secret-that-is-long-enough"
    body = b"RIFF" + b"bridge-audio" * 64
    observed: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.host == "api.runpod.ai" and http_request.method == "POST":
            document = json.loads(http_request.content)
            bridge = document["input"]["artifact_bridge"]
            observed["bridge"] = bridge
            assert bridge["schema"] == "aionex.open-song-artifact-bridge.v1"
            assert set(bridge["artifacts"]) == {
                "full_song", "vocals", "drums", "bass", "other"
            }
            for target in bridge["artifacts"].values():
                assert target["upload_url"].startswith(
                    f"https://{bridge_host}/api/v1/audio-song-artifacts/"
                )
                assert target["upload_token"] not in target["upload_url"]
            return httpx.Response(200, json={"id": "bridge-job-1", "status": "IN_QUEUE"})
        assert http_request.url.host == bridge_host
        assert "authorization" in http_request.headers
        if http_request.method == "GET":
            return httpx.Response(
                200,
                content=body,
                headers={
                    "content-type": "audio/wav",
                    "content-length": str(len(body)),
                },
            )
        if http_request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError("unexpected request")

    transport = httpx.MockTransport(handler)
    runtime = RunPodOpenSongAdapter(
        transport=transport,
        allowed_artifact_hosts={bridge_host},
        artifact_bridge_origin=f"https://{bridge_host}",
        artifact_bridge_secret=bridge_secret,
        artifact_bridge_ttl_seconds=600,
    )
    job = await runtime.submit(request(), credential=CREDENTIAL, endpoint_id=ENDPOINT_ID)
    assert job.job_id == "bridge-job-1"
    bridge = observed["bridge"]
    assert isinstance(bridge, dict)
    artifact_id = bridge["artifacts"]["full_song"]["artifact_id"]
    declared = ProviderAudioArtifact(
        url=None,
        artifact_id=artifact_id,
        sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
        media_type="audio/wav",
        duration_seconds=30.0,
        sample_rate_hz=48_000,
        channels=2,
    )
    downloaded = await runtime.download(declared)
    assert downloaded.sha256 == hashlib.sha256(body).hexdigest()
    assert await runtime.cleanup(declared) is True
    assert "upload_token" not in declared.public_snapshot()
    assert "artifact_id" not in declared.public_snapshot()


@pytest.mark.asyncio
async def test_poll_failed_job_preserves_only_sanitized_handler_error_code() -> None:
    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == f"/v2/{ENDPOINT_ID}/status/stage8-job-failed"
        return httpx.Response(
            200,
            json={
                "id": "stage8-job-failed",
                "status": "FAILED",
                "executionTime": 12_345,
                "error": "open_song_handler_failed:acestep_api_startup_exit",
            },
        )

    job = await adapter(handler).retrieve(
        "stage8-job-failed", credential=CREDENTIAL, endpoint_id=ENDPOINT_ID
    )
    assert job.state == "FAILED"
    assert job.result is None
    assert job.metadata["error_type"] == "open_song_handler_failed:acestep_api_startup_exit"
    assert job.metadata["executiontime"] == 12_345
    assert "credential" not in repr(job.metadata).lower()
