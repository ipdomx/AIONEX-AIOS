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
