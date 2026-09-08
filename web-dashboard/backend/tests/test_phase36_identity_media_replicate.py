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
