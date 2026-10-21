"""Pure HTTP-contract regression tests: no database, credentials, or network."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys

import httpx
import pytest

_PATH = (Path(__file__).resolve().parents[1] / "web-dashboard/backend/app/services/identity_media_replicate.py")
_SPEC = importlib.util.spec_from_file_location("_identity_submission_contract_adapter", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
adapter_module = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = adapter_module
_SPEC.loader.exec_module(adapter_module)

INVALID_BODIES = [
    b"not-json", b"[]", b'{"status":"starting"}',
    b'{"id":"job-contract"}', b'{"id":"job-contract","status":"unknown"}',
]


def submit(kind: str, transport: httpx.MockTransport):
    adapter = adapter_module.ReplicateIdentityMediaAdapter("contract-test-only", transport=transport)
    if kind == "model":
        return asyncio.run(adapter.create_prediction(model="minimax/voice-cloning", inputs={}))
    return asyncio.run(adapter.create_pinned_prediction(version=adapter_module.VOICE_TRANSFORM_VERSION, inputs={}))


def assert_single_post(requests, kind):
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.host == "api.replicate.com"
    assert request.url.path == ("/v1/models/minimax/voice-cloning/predictions" if kind == "model" else "/v1/predictions")


@pytest.mark.parametrize("kind", ["model", "pinned"])
@pytest.mark.parametrize("status", [200, 201])
@pytest.mark.parametrize("body", INVALID_BODIES)
def test_successful_post_with_invalid_receipt_requires_review(kind, status, body):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, content=body)
    with pytest.raises(adapter_module.IdentityMediaProviderFailure) as caught:
        submit(kind, httpx.MockTransport(handler))
    assert caught.value.code == "provider_response_invalid"
    assert caught.value.ambiguous_submission is True
    assert caught.value.retryable is False
    assert caught.value.http_status == status
    assert "contract-test-only" not in str(caught.value)
    assert_single_post(requests, kind)


@pytest.mark.parametrize("kind", ["model", "pinned"])
@pytest.mark.parametrize("status", [200, 201])
@pytest.mark.parametrize("state", ["starting", "processing", "succeeded", "failed", "canceled"])
def test_valid_creation_receipt_is_unchanged(kind, status, state):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"id": "job-contract", "status": state})
    result = submit(kind, httpx.MockTransport(handler))
    assert result.prediction_id == "job-contract"
    assert result.status == state
    assert_single_post(requests, kind)


@pytest.mark.parametrize("kind", ["model", "pinned"])
@pytest.mark.parametrize("status", [400, 401, 403, 422, 429, 500, 503])
def test_http_rejection_and_ambiguity_classification_is_preserved(kind, status):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"detail": "test response"})
    with pytest.raises(adapter_module.IdentityMediaProviderFailure) as caught:
        submit(kind, httpx.MockTransport(handler))
    assert caught.value.code == ("provider_submission_ambiguous" if status >= 500 else "provider_submission_rejected")
    assert caught.value.ambiguous_submission is (status >= 500)
    assert caught.value.retryable is False
    assert caught.value.http_status == status
    assert_single_post(requests, kind)


@pytest.mark.parametrize("kind", ["model", "pinned"])
@pytest.mark.parametrize("error_type", [httpx.ConnectTimeout, httpx.ReadTimeout])
def test_transport_failure_is_ambiguous_and_not_retried(kind, error_type):
    requests = []
    def handler(request):
        requests.append(request)
        raise error_type("contract timeout", request=request)
    with pytest.raises(adapter_module.IdentityMediaProviderFailure) as caught:
        submit(kind, httpx.MockTransport(handler))
    assert caught.value.code == "provider_submission_ambiguous"
    assert caught.value.ambiguous_submission is True
    assert caught.value.retryable is False
    assert_single_post(requests, kind)


@pytest.mark.parametrize("body", INVALID_BODIES)
def test_read_only_poll_does_not_gain_submission_ambiguity(body):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=body)
    adapter = adapter_module.ReplicateIdentityMediaAdapter("contract-test-only", transport=httpx.MockTransport(handler))
    with pytest.raises(adapter_module.IdentityMediaProviderFailure) as caught:
        asyncio.run(adapter.get_prediction("job-contract"))
    assert caught.value.code == "provider_response_invalid"
    assert caught.value.ambiguous_submission is False
    assert len(requests) == 1 and requests[0].method == "GET"
