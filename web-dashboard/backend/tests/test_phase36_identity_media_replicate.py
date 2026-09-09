from __future__ import annotations

import pytest

from app.services.identity_media_replicate import (
    IdentityMediaProviderFailure,
    ReplicateIdentityMediaAdapter,
    model_for_operation,
    trusted_output_url,
)
from app.services.identity_media_runtime import _cost_authorization


def test_runtime_model_catalog_is_bounded():
    assert model_for_operation("voice_clone") == "minimax/voice-cloning"
    assert model_for_operation("talking_head") == "prunaai/p-video-avatar"
    assert model_for_operation("lip_sync") == "sync/lipsync-2"
    with pytest.raises(IdentityMediaProviderFailure, match="identity_media_runtime_pending"):
        model_for_operation("face_swap")


def test_provider_output_download_is_restricted_to_replicate_delivery():
    assert trusted_output_url("https://replicate.delivery/pbxt/example/output.mp4").startswith(
        "https://replicate.delivery/"
    )
    assert trusted_output_url("https://abc.replicate.delivery/example.wav").startswith(
        "https://abc.replicate.delivery/"
    )
    for rejected in (
        "http://replicate.delivery/output.mp4",
        "https://replicate.delivery.evil.example/output.mp4",
        "https://example.com/output.mp4",
    ):
        with pytest.raises(IdentityMediaProviderFailure, match="provider_output_host_rejected"):
            trusted_output_url(rejected)


def test_provider_adapter_rejects_untrusted_base_url():
    with pytest.raises(IdentityMediaProviderFailure, match="provider_base_url_rejected"):
        ReplicateIdentityMediaAdapter("test-token", base_url="https://example.com")


def test_cost_value_is_authorization_not_invented_estimate():
    maximum, basis = _cost_authorization(5.0)
    assert maximum == 5.0
    assert basis == "user_authorized_ceiling_provider_price_unverified"
    with pytest.raises(Exception, match="outside the launch range"):
        _cost_authorization(0)
    with pytest.raises(Exception, match="outside the launch range"):
        _cost_authorization(25.01)


def test_provider_input_token_round_trip_and_tamper_rejection():
    from app.services.identity_media_replicate import (
        IdentityMediaProviderFailure,
        issue_provider_input_token,
        provider_input_url,
        verify_provider_input_token,
    )

    secret = "s" * 48
    token = issue_provider_input_token(
        execution_id="11111111-2222-3333-4444-555555555555",
        input_name="audio",
        secret=secret,
        ttl_seconds=300,
        now_epoch=1_800_000_000,
    )
    grant = verify_provider_input_token(
        token,
        secret=secret,
        now_epoch=1_800_000_100,
    )
    assert grant.execution_id == "11111111-2222-3333-4444-555555555555"
    assert grant.input_name == "audio"
    assert grant.expires_at_epoch == 1_800_000_300
    url = provider_input_url(
        "https://api.vip-e.net",
        token,
        "voice-reference.wav",
    )
    assert url.startswith("https://api.vip-e.net/api/v1/studio/identity-media/provider-input/")
    assert url.endswith("/voice-reference.wav")
    with pytest.raises(IdentityMediaProviderFailure, match="provider_input_token_invalid"):
        verify_provider_input_token(token[:-1] + ("0" if token[-1] != "0" else "1"), secret=secret, now_epoch=1_800_000_100)
    with pytest.raises(IdentityMediaProviderFailure, match="provider_input_token_expired"):
        verify_provider_input_token(token, secret=secret, now_epoch=1_800_000_301)


def test_provider_input_url_rejects_unsafe_origin_and_filename():
    from app.services.identity_media_replicate import (
        IdentityMediaProviderFailure,
        issue_provider_input_token,
        provider_input_url,
    )

    token = issue_provider_input_token(
        execution_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        input_name="audio",
        secret="k" * 48,
        ttl_seconds=300,
        now_epoch=1_800_000_000,
    )
    with pytest.raises(IdentityMediaProviderFailure, match="provider_input_origin_invalid"):
        provider_input_url("http://api.vip-e.net", token, "voice.wav")
    with pytest.raises(IdentityMediaProviderFailure, match="provider_input_filename_invalid"):
        provider_input_url("https://api.vip-e.net", token, "../voice.wav")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "input_name", "filename", "content_type"),
    [
        ("voice_clone", "audio", "voice-reference.wav", "audio/wav"),
        ("lip_sync", "video", "source-video.mp4", "video/mp4"),
        ("avatar_generation", "image", "fictional-avatar.png", "image/png"),
    ],
)
async def test_worker_uses_execution_scoped_signed_provider_pull(
    monkeypatch,
    operation: str,
    input_name: str,
    filename: str,
    content_type: str,
):
    from types import SimpleNamespace

    from app.services import identity_media_worker as worker_module

    class Store:
        def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
            assert key == f"identity-media/test/{input_name}"
            assert max_bytes == 100 * 1024 * 1024
            return b"validated-private-object"

    class Adapter:
        async def upload_private_file(self, **kwargs):
            raise AssertionError("bearer-protected provider file upload must not be used")

    worker = object.__new__(worker_module.IdentityMediaWorker)
    worker.store = Store()
    worker.adapter = Adapter()
    monkeypatch.setattr(
        worker_module,
        "settings",
        SimpleNamespace(
            IDENTITY_MEDIA_MAX_PROVIDER_BYTES=200 * 1024 * 1024,
            PORTAL_PUBLIC_API_ORIGIN="https://api.vip-e.net",
            SECRET_KEY="provider-input-test-secret-" + ("x" * 32),
        ),
    )
    row = SimpleNamespace(
        id="11111111-2222-3333-4444-555555555555",
        operation=operation,
        input_storage_keys={input_name: f"identity-media/test/{input_name}"},
        request_payload={
            "input_content_types": {input_name: content_type},
            "input_filenames": {input_name: filename},
        },
    )

    provider_file = await worker._input_file(row, input_name)

    assert provider_file.file_id == f"signed-provider-input:{input_name}"
    assert provider_file.url.startswith(
        "https://api.vip-e.net/api/v1/studio/identity-media/provider-input/"
    )
    assert provider_file.url.endswith(f"/{filename}")


@pytest.mark.asyncio
async def test_provider_input_endpoint_serves_only_active_bound_object(monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.api.v1.endpoints import identity_media as endpoint_module
    from app.services.identity_media_replicate import issue_provider_input_token

    secret = "provider-input-endpoint-test-secret-" + ("y" * 32)
    execution_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    token = issue_provider_input_token(
        execution_id=execution_id,
        input_name="audio",
        secret=secret,
        ttl_seconds=300,
    )
    row = SimpleNamespace(
        status="provider_running",
        input_storage_keys={"audio": "identity-media/test/audio"},
        request_payload={
            "input_content_types": {"audio": "audio/wav"},
            "input_filenames": {"audio": "voice-reference.wav"},
        },
    )

    class Session:
        async def scalar(self, statement):
            assert statement is not None
            return row

    class Store:
        def get_bytes(self, key: str, *, max_bytes: int) -> bytes:
            assert key == "identity-media/test/audio"
            assert max_bytes == 20 * 1024 * 1024
            return b"RIFF-test-audio"

    monkeypatch.setattr(
        endpoint_module,
        "settings",
        SimpleNamespace(
            SECRET_KEY=secret,
            IDENTITY_MEDIA_MAX_PROVIDER_BYTES=20 * 1024 * 1024,
        ),
    )
    monkeypatch.setattr(endpoint_module, "media_object_store", lambda: Store())
    async def allowed_access(*_args, **_kwargs):
        return SimpleNamespace(allowed=True)

    monkeypatch.setattr(
        endpoint_module.identity_media_access, "execution_access", allowed_access
    )

    response = await endpoint_module.provider_input(
        token=token,
        filename="voice-reference.wav",
        session=Session(),
    )

    assert response.body == b"RIFF-test-audio"
    assert response.media_type == "audio/wav"
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["x-content-type-options"] == "nosniff"

    row.status = "completed"
    with pytest.raises(HTTPException) as captured:
        await endpoint_module.provider_input(
            token=token,
            filename="voice-reference.wav",
            session=Session(),
        )
    assert captured.value.status_code == 404
