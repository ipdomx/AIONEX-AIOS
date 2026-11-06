"""Roadmap 0.3: unaccepted identity-media operations are gated; failures carry clear codes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import identity_media as endpoint_module
from app.services import identity_media_access
from app.services import identity_media_worker as worker_module
from app.services.identity_media_replicate import (
    IdentityMediaProviderFailure,
    _prediction,
    failure_code,
    sanitize_provider_error,
)
from app.services.identity_media_runtime import IdentityMediaClaim


def _actor(role: str = "Member") -> SimpleNamespace:
    return SimpleNamespace(
        id="user-gate",
        role=role,
        organization_id="org-gate",
        status="active",
    )


def test_unaccepted_operations_match_phase36_status_document():
    import json
    from pathlib import Path

    status = json.loads(
        (Path(__file__).resolve().parents[3] / "docs/phase-36/CURRENT_STATUS.json").read_text()
    )
    assert set(status["not_yet_accepted_operations"]) == set(
        identity_media_access.NOT_YET_ACCEPTED_OPERATIONS
    )


def test_unaccepted_operations_are_owner_only_unless_flag_is_on(monkeypatch):
    monkeypatch.setattr(
        identity_media_access.settings, "IDENTITY_MEDIA_UNACCEPTED_OPERATIONS_PUBLIC", False
    )
    member = _actor()
    owner = _actor("Super Owner")
    for operation in ("voice_transform", "face_swap"):
        assert identity_media_access.operation_available_to(member, operation) is False
        assert identity_media_access.operation_available_to(owner, operation) is True
    assert identity_media_access.operation_available_to(member, "voice_clone") is True
    monkeypatch.setattr(
        identity_media_access.settings, "IDENTITY_MEDIA_UNACCEPTED_OPERATIONS_PUBLIC", True
    )
    assert identity_media_access.operation_available_to(member, "voice_transform") is True


@pytest.mark.asyncio
async def test_capabilities_mark_unaccepted_operations_pending_for_members(monkeypatch):
    monkeypatch.setattr(
        identity_media_access.settings, "IDENTITY_MEDIA_UNACCEPTED_OPERATIONS_PUBLIC", False
    )

    async def billing_context(_session, _organization_id):
        return {"account": SimpleNamespace(status="active")}

    class Session:
        async def scalars(self, _statement):
            return SimpleNamespace(all=lambda: [])

    monkeypatch.setattr(identity_media_access.billing, "billing_context", billing_context)
    snapshot = await identity_media_access.user_access_snapshot(Session(), _actor())
    rows = {row["operation"]: row for row in snapshot["operations"]}
    assert rows["voice_transform"]["runtime_ready"] is False
    assert rows["voice_transform"]["acceptance_pending"] is True
    assert rows["voice_transform"]["accepted"] is False
    assert rows["face_swap"]["acceptance_pending"] is True
    assert rows["voice_clone"]["runtime_ready"] is True
    assert rows["voice_clone"]["acceptance_pending"] is False


@pytest.mark.asyncio
async def test_member_cannot_submit_unaccepted_operation(monkeypatch):
    monkeypatch.setattr(endpoint_module.settings, "IDENTITY_MEDIA_LIVE_ENABLED", True)
    monkeypatch.setattr(endpoint_module.settings, "REPLICATE_API_TOKEN", "configured-token")
    monkeypatch.setattr(
        identity_media_access.settings, "IDENTITY_MEDIA_UNACCEPTED_OPERATIONS_PUBLIC", False
    )
    for operation in ("voice_transform", "face_swap"):
        with pytest.raises(HTTPException) as caught:
            await endpoint_module.create_identity_execution(
                operation=operation,
                identity_basis="fictional_inspired",
                subject_reference="original character",
                idempotency_key="gate-test-0001",
                synthetic_media_disclosure_accepted=True,
                approved_max_cost_usd=1.0,
                actor=_actor(),
                session=None,
            )
        assert caught.value.status_code == 403
        assert caught.value.detail["code"] == "IDENTITY_MEDIA_OPERATION_NOT_ACCEPTED"
        assert caught.value.detail["operation"] == operation


@pytest.mark.asyncio
async def test_runtime_gates_return_machine_readable_codes(monkeypatch):
    monkeypatch.setattr(endpoint_module.settings, "IDENTITY_MEDIA_LIVE_ENABLED", False)
    with pytest.raises(HTTPException) as not_live:
        await endpoint_module.create_identity_execution(
            operation="voice_clone",
            identity_basis="fictional_inspired",
            subject_reference="original character",
            idempotency_key="gate-test-0002",
            synthetic_media_disclosure_accepted=True,
            approved_max_cost_usd=1.0,
            actor=_actor(),
            session=None,
        )
    assert not_live.value.detail["code"] == "IDENTITY_MEDIA_RUNTIME_NOT_LIVE"
    monkeypatch.setattr(endpoint_module.settings, "IDENTITY_MEDIA_LIVE_ENABLED", True)
    monkeypatch.setattr(endpoint_module.settings, "REPLICATE_API_TOKEN", "")
    with pytest.raises(HTTPException) as unconfigured:
        await endpoint_module.create_identity_execution(
            operation="voice_clone",
            identity_basis="fictional_inspired",
            subject_reference="original character",
            idempotency_key="gate-test-0003",
            synthetic_media_disclosure_accepted=True,
            approved_max_cost_usd=1.0,
            actor=_actor(),
            session=None,
        )
    assert unconfigured.value.detail["code"] == "IDENTITY_MEDIA_PROVIDER_NOT_CONFIGURED"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "provider_auth_rejected"),
        (402, "provider_billing_required"),
        (403, "provider_auth_rejected"),
        (404, "provider_model_not_found"),
        (422, "provider_input_rejected"),
        (429, "provider_rate_limited"),
        (418, "provider_submission_rejected"),
    ],
)
def test_rejected_submission_codes_name_the_http_cause(status, expected):
    exc = IdentityMediaProviderFailure("provider_submission_rejected", http_status=status)
    assert failure_code(exc) == expected
    ambiguous = IdentityMediaProviderFailure(
        "provider_submission_ambiguous", ambiguous_submission=True, http_status=502
    )
    assert failure_code(ambiguous) == "provider_submission_ambiguous"


def test_provider_error_excerpt_drops_urls_and_tokens():
    prediction = _prediction(
        {
            "id": "p1",
            "status": "failed",
            "error": "Could not download https://api.example.test/provider-input/abc.def/in.wav "
            "with Bearer r8_SECRETSECRETSECRETSECRET",
        }
    )
    assert prediction.error_present is True
    assert prediction.error_excerpt is not None
    assert "https://" not in prediction.error_excerpt
    assert "r8_SECRET" not in prediction.error_excerpt
    assert "Could not download" in prediction.error_excerpt
    assert sanitize_provider_error(None) is None


class _Session:
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
        "organization_id": "org-gate",
        "requested_by_id": "user-gate",
        "operation": "lip_sync",
        "identity_basis": "fictional_inspired",
        "provider_job_id": "prediction-1",
        "secondary_provider_job_id": None,
        "provider_state": "processing",
        "request_payload": {},
        "input_storage_keys": {"video": "v", "audio": "a"},
        "model": "sync/lipsync-2",
        "status": "provider_running",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _worker(monkeypatch, row, adapter):
    monkeypatch.setattr(worker_module, "SessionLocal", lambda: _Session())
    monkeypatch.setattr(worker_module, "load_claim", AsyncMock(return_value=row))
    fail = AsyncMock()
    release = AsyncMock()
    monkeypatch.setattr(worker_module, "fail_execution", fail)
    monkeypatch.setattr(worker_module, "release_for_poll", release)
    worker = object.__new__(worker_module.IdentityMediaWorker)
    worker.adapter = adapter
    worker.poll_seconds = 3
    worker._authorized = AsyncMock(return_value=True)
    return worker, fail, release


@pytest.mark.asyncio
async def test_transient_poll_error_keeps_polling_instead_of_failing(monkeypatch):
    adapter = SimpleNamespace(
        get_prediction=AsyncMock(
            side_effect=IdentityMediaProviderFailure("provider_poll_failed", retryable=True)
        )
    )
    worker, fail, release = _worker(monkeypatch, _row(), adapter)
    await worker._poll(IdentityMediaClaim("11111111-2222-3333-4444-555555555555", "k", 1, "poll"))
    fail.assert_not_awaited()
    release.assert_awaited_once()
    assert release.await_args.kwargs["provider_state"] == "processing"


@pytest.mark.asyncio
async def test_failed_prediction_records_code_and_sanitized_provider_error(monkeypatch):
    prediction = _prediction(
        {"id": "prediction-1", "status": "failed", "error": "input video has no face https://x.test/a"}
    )
    adapter = SimpleNamespace(get_prediction=AsyncMock(return_value=prediction))
    worker, fail, release = _worker(monkeypatch, _row(), adapter)
    await worker._poll(IdentityMediaClaim("11111111-2222-3333-4444-555555555555", "k", 1, "poll"))
    release.assert_not_awaited()
    kwargs = fail.await_args.kwargs
    assert kwargs["code"] == "provider_execution_failed"
    assert "input video has no face" in kwargs["message"]
    assert "https://" not in kwargs["message"]


@pytest.mark.asyncio
async def test_rejected_submission_stores_http_specific_code(monkeypatch):
    row = _row(provider_job_id=None, status="queued", provider_state="not_started")
    adapter = SimpleNamespace(
        create_prediction=AsyncMock(
            side_effect=IdentityMediaProviderFailure("provider_submission_rejected", http_status=402)
        )
    )
    worker, fail, _release = _worker(monkeypatch, row, adapter)
    worker._input_file = AsyncMock(return_value=SimpleNamespace(url="https://portal.test/in"))
    await worker._submit(IdentityMediaClaim(row.id, "k", 1, "submit"))
    kwargs = fail.await_args.kwargs
    assert kwargs["code"] == "provider_billing_required"
    assert "HTTP 402" in kwargs["message"]
    assert kwargs["needs_review"] is False
