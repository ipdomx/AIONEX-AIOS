"""RunPod paused/auth failures are permanent, sanitized and never retried."""

from __future__ import annotations

import io
import json
import urllib.error
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from aios.gpu_worker import runpod as runpod_module
from aios.gpu_worker.runpod import RunPodError, RunPodServerlessClient
from app.db.base import SessionLocal
from app.db.models import OwnerControlRecord
from app.services import three_d_worker
from app.services.three_d_resilience import (
    PROVIDER_STATE_DOMAIN,
    assert_provider_available,
    provider_circuit_snapshot,
    record_provider_failure,
    record_provider_paused,
    record_provider_success,
)

API_KEY = "rpa_TESTSECRETKEY0123456789ABCDEFGHIJKLMNOP"


def _http_error(status: int, body: object) -> urllib.error.HTTPError:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return urllib.error.HTTPError(
        "https://api.runpod.ai/v2/endpoint/run", status, "error", {}, io.BytesIO(raw)
    )


def _submit_with(monkeypatch, error: urllib.error.HTTPError) -> RunPodError:
    def fail(_request, timeout):  # noqa: ARG001 - urllib signature
        raise error

    monkeypatch.setattr(runpod_module.urllib.request, "urlopen", fail)
    client = RunPodServerlessClient(API_KEY, "endpoint-primary")
    with pytest.raises(RunPodError) as caught:
        client.submit({"image": "x"})
    return caught.value


def test_paused_endpoint_is_permanent_with_status_and_code(monkeypatch):
    exc = _submit_with(
        monkeypatch,
        _http_error(409, {"error": "Endpoint is paused (max_workers=0)", "code": "ENDPOINT_PAUSED"}),
    )
    assert exc.status == 409
    assert exc.code == "ENDPOINT_PAUSED"
    assert exc.category == "paused" and exc.permanent is True
    assert "HTTP 409" in str(exc) and "ENDPOINT_PAUSED" in str(exc)
    assert "Endpoint is paused (max_workers=0)" in str(exc)
    assert API_KEY not in str(exc)
    assert exc.safe_details() == {
        "http_status": 409,
        "provider_error_code": "ENDPOINT_PAUSED",
        "provider_error_message": "Endpoint is paused (max_workers=0)",
        "error_category": "paused",
    }


def test_paused_message_without_code_is_still_classified(monkeypatch):
    exc = _submit_with(monkeypatch, _http_error(409, {"error": "Endpoint is paused (max_workers=0)"}))
    assert exc.code == "ENDPOINT_PAUSED" and exc.permanent


@pytest.mark.parametrize("status", [401, 403])
def test_auth_rejections_are_permanent_and_redacted(monkeypatch, status):
    exc = _submit_with(
        monkeypatch,
        _http_error(status, {"error": f"invalid api key Bearer {API_KEY} token={API_KEY}"}),
    )
    assert exc.status == status
    assert exc.category == "auth" and exc.permanent
    assert API_KEY not in str(exc)
    assert API_KEY not in json.dumps(exc.safe_details())
    assert "[redacted]" in str(exc)


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_transient_statuses_stay_retryable(monkeypatch, status):
    exc = _submit_with(monkeypatch, _http_error(status, b"<html>upstream</html>"))
    assert exc.status == status
    assert exc.category == "transient" and exc.permanent is False


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def commit(self):
        return None


class _Storage:
    def get_bytes(self, _key, *, max_bytes):
        assert max_bytes > 0
        return b"image"


async def _policy(_session):
    return {
        "enabled": True,
        "max_queue_seconds": 30,
        "max_runtime_seconds": 60,
        "max_input_megabytes": 8,
        "max_texture_size": 1024,
        "compression_policy": "compat",
    }


def _worker(monkeypatch, error: RunPodError):
    calls: dict[str, list] = {"failed": [], "transient": [], "paused": []}

    class Client:
        endpoint_id = "endpoint-fallback"

        def submit(self, _payload, *, ttl_seconds):
            assert ttl_seconds > 0
            raise error

    job = SimpleNamespace(
        id="job-1",
        trace_id="trace-1",
        status="queued",
        provider="triposr",
        provider_job_id=None,
        input_object_key="private/in.png",
        request_options={},
    )
    worker = object.__new__(three_d_worker.ThreeDGenerationWorker)
    worker.storage = _Storage()
    worker.runpods = {"triposr": Client()}
    worker.last_provider_failure_at = None

    async def load(_job_id, _lease):
        return job

    async def failed(job_id, lease, code, message, *, retryable, provider_detail=None):
        calls["failed"].append((code, message, retryable, provider_detail))

    async def transient(_job, code):
        calls["transient"].append(code)

    async def available(_session, *, provider):
        return {"state": "closed", "paused": False}

    async def paused(_session, **kwargs):
        calls["paused"].append(kwargs)
        return {}

    worker._load = load
    worker._failed = failed
    worker._provider_failure = transient
    monkeypatch.setattr(three_d_worker, "SessionLocal", _Session)
    monkeypatch.setattr(three_d_worker, "get_three_d_policy", _policy)
    monkeypatch.setattr(three_d_worker, "assert_provider_available", available)
    monkeypatch.setattr(three_d_worker, "record_provider_paused", paused)
    return worker, calls


@pytest.mark.asyncio
async def test_worker_fails_paused_submission_without_retry_or_circuit(monkeypatch):
    error = RunPodError.from_http(
        "RunPod Serverless",
        409,
        json.dumps({"error": "Endpoint is paused (max_workers=0)", "code": "ENDPOINT_PAUSED"}).encode(),
    )
    worker, calls = _worker(monkeypatch, error)
    await worker.execute("job-1", "lease-1")
    assert calls["transient"] == []
    assert calls["paused"] == [
        {
            "error_code": "THREE_D_PROVIDER_PAUSED",
            "provider": "triposr",
            "http_status": 409,
            "provider_error_code": "ENDPOINT_PAUSED",
        }
    ]
    [(code, message, retryable, detail)] = calls["failed"]
    assert code == "THREE_D_PROVIDER_PAUSED"
    assert retryable is False
    assert "HTTP 409 ENDPOINT_PAUSED" in message and "temporarily unavailable" in message
    assert detail["http_status"] == 409 and detail["provider_error_code"] == "ENDPOINT_PAUSED"


@pytest.mark.asyncio
async def test_worker_fails_auth_rejection_with_auth_code(monkeypatch):
    error = RunPodError.from_http("RunPod Serverless", 401, b'{"error": "Unauthorized"}')
    worker, calls = _worker(monkeypatch, error)
    await worker.execute("job-1", "lease-1")
    assert calls["transient"] == []
    [(code, message, retryable, detail)] = calls["failed"]
    assert code == "THREE_D_PROVIDER_AUTH" and retryable is False
    assert "HTTP 401" in message and detail["error_category"] == "auth"


@pytest.mark.asyncio
async def test_worker_transient_submit_failure_keeps_bounded_retry(monkeypatch):
    error = RunPodError.from_http("RunPod Serverless", 502, b"bad gateway")
    worker, calls = _worker(monkeypatch, error)
    await worker.execute("job-1", "lease-1")
    assert calls["paused"] == []
    assert calls["transient"] == ["THREE_D_SUBMIT_FAILED"]
    [(code, message, retryable, detail)] = calls["failed"]
    assert code == "THREE_D_SUBMIT_FAILED" and retryable is True
    assert "HTTP 502" in message and detail["http_status"] == 502


async def _reset_provider_rows(session) -> None:
    await session.execute(
        delete(OwnerControlRecord).where(OwnerControlRecord.domain == PROVIDER_STATE_DOMAIN)
    )
    await session.commit()


@pytest.mark.asyncio
async def test_paused_state_blocks_without_counting_failures_and_expires():
    async with SessionLocal() as session:
        await _reset_provider_rows(session)
        try:
            await record_provider_failure(session, error_code="TEST_TRANSIENT", provider="triposr")
            await session.commit()
            state = await record_provider_paused(
                session,
                error_code="THREE_D_PROVIDER_PAUSED",
                provider="triposr",
                http_status=409,
                provider_error_code="ENDPOINT_PAUSED",
            )
            await session.commit()
            assert state["paused"] is True
            assert state["consecutive_failures"] == 1  # unchanged by the pause
            assert state["state"] == "closed"
            with pytest.raises(HTTPException) as blocked:
                await assert_provider_available(session, provider="triposr")
            assert blocked.value.status_code == 503
            assert blocked.value.detail["code"] == "THREE_D_PROVIDER_PAUSED"
            assert blocked.value.detail["provider_state"] == "paused"
            # The primary endpoint is independent, so routing can fail over.
            primary = await assert_provider_available(session, provider="hunyuan3d")
            assert primary["available"] is True
            await session.commit()

            record = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == PROVIDER_STATE_DOMAIN,
                    OwnerControlRecord.resource_id == "triposr",
                )
            )
            from app.services.three_d_resilience import now

            payload = dict(record.payload)
            payload["paused_until"] = (now() - timedelta(seconds=1)).isoformat()
            record.payload = payload
            await session.commit()
            expired = await provider_circuit_snapshot(session, provider="triposr", lock=True)
            assert expired["paused"] is False and expired["available"] is True
            await session.commit()

            await record_provider_paused(
                session, error_code="THREE_D_PROVIDER_AUTH", provider="triposr", http_status=401
            )
            await session.commit()
            with pytest.raises(HTTPException) as auth:
                await assert_provider_available(session, provider="triposr")
            assert auth.value.detail["code"] == "THREE_D_PROVIDER_AUTH"
            cleared = await record_provider_success(session, provider="triposr")
            assert cleared["paused"] is False and cleared["consecutive_failures"] == 0
            await session.commit()
            with pytest.raises(ValueError):
                await record_provider_paused(session, error_code="THREE_D_SUBMIT_FAILED")
        finally:
            await session.rollback()
            await _reset_provider_rows(session)


@pytest.mark.asyncio
async def test_access_route_fails_over_from_paused_primary_and_reports_paused(monkeypatch):
    from app.api.v1.endpoints import three_d_jobs

    states = {"hunyuan3d": "THREE_D_PROVIDER_PAUSED", "triposr": None}

    async def configured(_provider):
        return True

    async def country(_session, _actor, _request):
        return "US", "cloudflare"

    async def available(_session, *, provider):
        code = states[provider]
        if code:
            raise HTTPException(status_code=503, detail={"code": code})
        return {"available": True}

    monkeypatch.setattr(three_d_jobs, "provider_runtime_configured", configured)
    monkeypatch.setattr(three_d_jobs, "request_country", country)
    monkeypatch.setattr(three_d_jobs, "assert_provider_available", available)
    monkeypatch.setattr(three_d_jobs, "provider_candidates", lambda _p, _c: ["hunyuan3d", "triposr"])
    monkeypatch.setattr(three_d_jobs, "provider_disclosure", lambda _p, provider: {"provider": provider})

    request = SimpleNamespace(state=SimpleNamespace())
    provider, _country, _source, disclosure = await three_d_jobs._licensed_provider_route(
        None, None, request, {}
    )
    assert provider == "triposr" and disclosure == {"provider": "triposr"}
    assert request.state.three_d_provider_route == {
        "provider_state": "available",
        "provider_failover": True,
        "provider_states": {"hunyuan3d": "paused", "triposr": "available"},
    }

    states["triposr"] = "THREE_D_PROVIDER_PAUSED"
    with pytest.raises(HTTPException) as unavailable:
        await three_d_jobs._licensed_provider_route(None, None, SimpleNamespace(state=SimpleNamespace()), {})
    assert unavailable.value.status_code == 503
    detail = unavailable.value.detail
    assert detail["code"] == "THREE_D_PROVIDERS_UNAVAILABLE"
    assert detail["provider_state"] == "paused" and detail["queueing"] is False

    states["triposr"] = "THREE_D_PROVIDER_CIRCUIT_OPEN"
    with pytest.raises(HTTPException) as mixed:
        await three_d_jobs._licensed_provider_route(None, None, SimpleNamespace(state=SimpleNamespace()), {})
    assert mixed.value.detail["provider_state"] == "unavailable"
