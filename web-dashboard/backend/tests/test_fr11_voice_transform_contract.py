from __future__ import annotations

import asyncio
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import httpx
import pytest

from app.api.v1.endpoints import identity_media as endpoint_module
from app.services import identity_media_access
from app.services import identity_media_worker as worker_module
from app.services.identity_media_replicate import (
    IdentityMediaProviderFailure,
    ReplicateIdentityMediaAdapter,
    VOICE_TRANSFORM_MODEL,
    VOICE_TRANSFORM_VERSION,
    issue_provider_input_token,
    model_for_operation,
    verify_provider_input_token,
)
from app.services.identity_media_runtime import IdentityMediaClaim


CONTENT_URL = (
    "https://api.vip-e.net/api/v1/studio/identity-media/provider-input/"
    "signed-content/content.wav"
)
TARGET_URL = (
    "https://api.vip-e.net/api/v1/studio/identity-media/provider-input/"
    "signed-target/target.wav"
)


class Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def commit(self):
        return None

    async def rollback(self):
        return None


def _row(**overrides):
    values = {
        "id": "11111111-2222-3333-4444-555555555555",
        "organization_id": "org-fr11",
        "requested_by_id": "user-fr11",
        "operation": "voice_transform",
        "identity_basis": "consented_person",
        "subject_reference": "consented-target-voice",
        "provider_job_id": None,
        "secondary_provider_job_id": None,
        "request_payload": {},
        "input_storage_keys": {
            "audio": "identity-media/fr11/content.wav",
            "target_voice": "identity-media/fr11/target.wav",
        },
        "status": "queued",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _worker_harness(monkeypatch, row):
    session = Session()
    monkeypatch.setattr(worker_module, "SessionLocal", lambda: session)
    monkeypatch.setattr(worker_module, "load_claim", AsyncMock(return_value=row))
    monkeypatch.setattr(worker_module, "record_primary_submission", AsyncMock())
    monkeypatch.setattr(worker_module, "fail_execution", AsyncMock())

    adapter = SimpleNamespace(
        create_pinned_prediction=AsyncMock(
            return_value=SimpleNamespace(
                prediction_id="prediction-fr11",
                status="starting",
                metrics={},
            )
        ),
        get_prediction=AsyncMock(),
        download_output=AsyncMock(),
    )
    worker = object.__new__(worker_module.IdentityMediaWorker)
    worker.adapter = adapter
    worker.poll_seconds = 3
    worker._input_file = AsyncMock(
        side_effect=[
            SimpleNamespace(url=CONTENT_URL),
            SimpleNamespace(url=TARGET_URL),
        ]
    )
    worker._authorized = AsyncMock(return_value=True)
    claim = IdentityMediaClaim(row.id, "worker-fr11", 1, "submit")
    return worker, adapter, claim


def test_voice_transform_is_pinned_and_admitted_only_through_runtime_contract() -> None:
    assert VOICE_TRANSFORM_MODEL == "adirik/hierspeechpp"
    assert (
        VOICE_TRANSFORM_VERSION
        == "ff5bcc71dc2c44662291fc348b9ca2eb40107c9f4b377b169fc0dea950c388c8"
    )
    assert model_for_operation("voice_transform") == VOICE_TRANSFORM_MODEL
    assert "voice_transform" in identity_media_access.RUNTIME_READY_OPERATIONS
    assert endpoint_module._RUNTIME_MODELS["voice_transform"] == VOICE_TRANSFORM_MODEL

    parameters = inspect.signature(endpoint_module.create_identity_execution).parameters
    assert "source_audio" in parameters
    assert "target_voice_audio" in parameters


def test_target_voice_has_an_execution_scoped_signed_provider_input_grant() -> None:
    secret = "fr11-provider-input-secret-" + ("x" * 40)
    token = issue_provider_input_token(
        execution_id="11111111-2222-3333-4444-555555555555",
        input_name="target_voice",
        secret=secret,
        ttl_seconds=300,
        now_epoch=1_800_000_000,
    )
    grant = verify_provider_input_token(
        token,
        secret=secret,
        now_epoch=1_800_000_100,
    )
    assert grant.input_name == "target_voice"
    assert grant.execution_id == "11111111-2222-3333-4444-555555555555"


def test_pinned_voice_transform_submission_uses_exact_schema_once() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url.path == "/v1/predictions"
        payload = json.loads(request.content)
        assert payload == {
            "version": VOICE_TRANSFORM_VERSION,
            "input": {
                "input_sound": CONTENT_URL,
                "target_voice": TARGET_URL,
                "denoise_ratio": 0.0,
                "text_to_vector_temperature": 0.33,
                "voice_conversion_temperature": 0.33,
                "output_sample_rate": 16000,
                "scale_output_volume": False,
            },
        }
        return httpx.Response(
            201,
            json={
                "id": "prediction-fr11",
                "status": "starting",
                "output": None,
                "metrics": {},
            },
        )

    adapter = ReplicateIdentityMediaAdapter(
        "test-token",
        transport=httpx.MockTransport(handler),
    )
    prediction = asyncio.run(
        adapter.create_pinned_prediction(
            version=VOICE_TRANSFORM_VERSION,
            inputs={
                "input_sound": CONTENT_URL,
                "target_voice": TARGET_URL,
                "denoise_ratio": 0.0,
                "text_to_vector_temperature": 0.33,
                "voice_conversion_temperature": 0.33,
                "output_sample_rate": 16000,
                "scale_output_volume": False,
            },
        )
    )
    assert prediction.prediction_id == "prediction-fr11"
    assert len(requests) == 1

    with pytest.raises(
        IdentityMediaProviderFailure,
        match="provider_model_version_rejected",
    ):
        asyncio.run(
            adapter.create_pinned_prediction(
                version="0" * 64,
                inputs={},
            )
        )
    assert len(requests) == 1


@pytest.mark.parametrize("failure_mode", ["timeout", "server"])
def test_ambiguous_voice_transform_submission_is_never_replayed(
    failure_mode: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure_mode == "timeout":
            raise httpx.ReadTimeout("lost response", request=request)
        return httpx.Response(503, json={"detail": "unavailable"})

    adapter = ReplicateIdentityMediaAdapter(
        "test-token",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(
        IdentityMediaProviderFailure,
        match="provider_submission_ambiguous",
    ) as caught:
        asyncio.run(
            adapter.create_pinned_prediction(
                version=VOICE_TRANSFORM_VERSION,
                inputs={
                    "input_sound": CONTENT_URL,
                    "target_voice": TARGET_URL,
                },
            )
        )

    assert calls == 1
    assert caught.value.ambiguous_submission is True


def test_voice_transform_output_is_validated_as_audio_not_video() -> None:
    assert worker_module._output_media(
        "voice_transform",
        b"ID3" + b"x" * 32,
        "application/octet-stream",
    ) == ("audio/mpeg", ".mp3")
    assert worker_module._output_media(
        "voice_transform",
        b"RIFF" + (b"x" * 4) + b"WAVE" + b"x" * 32,
        "audio/wav",
    ) == ("audio/wav", ".wav")

    with pytest.raises(
        IdentityMediaProviderFailure,
        match="provider_audio_envelope_rejected",
    ):
        worker_module._output_media(
            "voice_transform",
            b"not-audio",
            "application/octet-stream",
        )


def test_worker_requires_both_audio_inputs_and_reauthorizes_before_submission(
    monkeypatch,
) -> None:
    row = _row()
    worker, adapter, claim = _worker_harness(monkeypatch, row)

    asyncio.run(worker._submit(claim))

    assert worker._input_file.await_args_list == [
        call(row, "audio"),
        call(row, "target_voice"),
    ]
    assert worker._authorized.await_count == 2
    adapter.create_pinned_prediction.assert_awaited_once_with(
        version=VOICE_TRANSFORM_VERSION,
        inputs={
            "input_sound": CONTENT_URL,
            "target_voice": TARGET_URL,
            "denoise_ratio": 0.0,
            "text_to_vector_temperature": 0.33,
            "voice_conversion_temperature": 0.33,
            "output_sample_rate": 16000,
            "scale_output_volume": False,
        },
        cancel_after_seconds=600,
    )
    worker_module.record_primary_submission.assert_awaited_once()
    metadata = worker_module.record_primary_submission.await_args.kwargs[
        "provider_metadata"
    ]
    assert metadata["provider_input_names"] == ["audio", "target_voice"]
    assert metadata["provider_model_version"] == VOICE_TRANSFORM_VERSION
    assert metadata["automatic_submission_replay"] is False


def test_revocation_after_input_preflight_prevents_provider_submission(
    monkeypatch,
) -> None:
    row = _row()
    worker, adapter, claim = _worker_harness(monkeypatch, row)
    worker._authorized.side_effect = [True, False]

    asyncio.run(worker._submit(claim))

    assert worker._input_file.await_count == 2
    adapter.create_pinned_prediction.assert_not_awaited()
    worker_module.record_primary_submission.assert_not_awaited()
