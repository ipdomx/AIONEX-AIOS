"""Offline diagnostics contracts: no credentials, external requests or database writes."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.core.config import settings
from app.services import telegram_worker as module

FAKE_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi"
PRIVATE_MARKER = "private-request-payload-must-not-be-logged"


def call_with_transport(handler):
    async def exercise():
        api = module.TelegramBotAPI(FAKE_TOKEN)
        await api._client.aclose()
        api._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await api._call("getMe", {})
        finally:
            await api.close()
    return asyncio.run(exercise())


@pytest.mark.parametrize("exception_type,expected_code", [
    (httpx.ConnectTimeout, "telegram_connect_timeout"),
    (httpx.ReadTimeout, "telegram_read_timeout"),
    (httpx.WriteTimeout, "telegram_write_timeout"),
    (httpx.PoolTimeout, "telegram_pool_timeout"),
    (httpx.TimeoutException, "telegram_timeout"),
    (httpx.ConnectError, "telegram_network_error"),
    (httpx.ReadError, "telegram_network_error"),
    (httpx.WriteError, "telegram_network_error"),
])
def test_transport_error_has_bounded_code_without_request_material(exception_type, expected_code):
    calls = []
    def handler(request):
        calls.append(request)
        raise exception_type(FAKE_TOKEN + PRIVATE_MARKER, request=request)
    with pytest.raises(module.TelegramWorkerError) as raised:
        call_with_transport(handler)
    error = raised.value
    assert error.code == expected_code
    assert error.http_status is None
    assert FAKE_TOKEN not in str(error)
    assert PRIVATE_MARKER not in str(error)
    assert len(calls) == 1  # No additional request, retry or acknowledgement.


@pytest.mark.parametrize("status", [400, 401, 403, 409, 429, 500, 503])
def test_http_error_records_only_status_without_response_body(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=FAKE_TOKEN + PRIVATE_MARKER)
    with pytest.raises(module.TelegramWorkerError) as raised:
        call_with_transport(handler)
    assert raised.value.code == "telegram_http_error"
    assert raised.value.http_status == status
    assert FAKE_TOKEN not in str(raised.value)
    assert PRIVATE_MARKER not in str(raised.value)
    assert len(calls) == 1


@pytest.mark.parametrize("body,code", [
    (b"not-json", "telegram_invalid_json"),
    (b"[]", "telegram_request_rejected"),
    (b"null", "telegram_request_rejected"),
    (b'{"ok": false, "description": "private-request-payload-must-not-be-logged"}', "telegram_request_rejected"),
    (b'{"result": {}}', "telegram_request_rejected"),
])
def test_invalid_acknowledgement_is_classified_without_echo(body, code):
    with pytest.raises(module.TelegramWorkerError) as raised:
        call_with_transport(lambda request: httpx.Response(200, content=body))
    assert raised.value.code == code
    assert raised.value.http_status == 200
    assert PRIVATE_MARKER not in str(raised.value)


@pytest.mark.parametrize("result", [{"id": 1}, [], True, None])
def test_success_contract_is_unchanged(result):
    assert call_with_transport(lambda request: httpx.Response(200, json={"ok": True, "result": result})) == {"result": result}


@pytest.mark.parametrize("untrusted_code,untrusted_status", [
    (FAKE_TOKEN, 200), (PRIVATE_MARKER, 700), ("https://example.test/private", True),
    ([], "401"), (None, -1), ("telegram_read_timeout", False),
])
def test_diagnostic_fields_reject_arbitrary_values(untrusted_code, untrusted_status):
    error = module.TelegramWorkerError(PRIVATE_MARKER, code=untrusted_code, http_status=untrusted_status)
    assert error.code in module._FAILURE_CODES
    assert FAKE_TOKEN not in error.code and PRIVATE_MARKER not in error.code
    assert error.http_status == (200 if type(untrusted_status) is int and untrusted_status == 200 else None)


def configured_worker(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(settings, "AIOS_TELEGRAM_HEALTH_FILE", str(tmp_path / "health.json"))
    monkeypatch.setattr(settings, "AIOS_TELEGRAM_ALLOWED_USERS", [1001])
    logger = Mock()
    monkeypatch.setattr(module, "logger", logger)
    return module.TelegramOperationsWorker(Mock()), logger


@pytest.mark.parametrize("code,http_status", [
    ("telegram_read_timeout", None), ("telegram_http_error", 401),
    ("telegram_http_error", 409), ("telegram_http_error", 429),
])
def test_last_failure_survives_recovery_without_weakening_health(monkeypatch, tmp_path, code, http_status):
    worker, logger = configured_worker(monkeypatch, tmp_path)
    worker._record_failure(module.TelegramWorkerError(FAKE_TOKEN + PRIVATE_MARKER, code=code, http_status=http_status))
    worker._write_health("degraded", offset=0)
    assert module.healthcheck(worker.health_path) == 1
    before = json.loads(worker.health_path.read_text())
    assert before["errors"] == 1 and before["last_error_code"] == code
    assert before["last_error_http_status"] == http_status
    assert datetime.fromisoformat(before["last_error_at"]).tzinfo is not None
    assert worker.health_path.stat().st_mode & 0o777 == 0o600
    worker._write_health("running", offset=0)
    assert module.healthcheck(worker.health_path) == 0
    after = json.loads(worker.health_path.read_text())
    assert after["last_error_code"] == code and after["last_error_at"] == before["last_error_at"]
    assert after["errors"] == 1
    assert FAKE_TOKEN not in worker.health_path.read_text()
    assert PRIVATE_MARKER not in worker.health_path.read_text()
    logger.warning.assert_called_once_with("Telegram polling failure", error="TelegramWorkerError", error_code=code, http_status=http_status)
    assert PRIVATE_MARKER not in str(logger.mock_calls)
    assert FAKE_TOKEN not in str(logger.mock_calls)


def test_initial_state_does_not_invent_an_incident(monkeypatch, tmp_path):
    worker, logger = configured_worker(monkeypatch, tmp_path)
    worker._write_health("running", offset=0)
    health = json.loads(worker.health_path.read_text())
    assert health["errors"] == 0
    assert health["last_error_code"] is None
    assert health["last_error_http_status"] is None
    assert health["last_error_at"] is None
    logger.warning.assert_not_called()


def test_real_poll_loop_preserves_failure_then_success_without_extra_replays(monkeypatch, tmp_path):
    worker, logger = configured_worker(monkeypatch, tmp_path)
    states = []
    write_health = worker._write_health
    def capture(status, *, offset):
        states.append(status)
        write_health(status, offset=offset)
    monkeypatch.setattr(worker, "_write_health", capture)
    monkeypatch.setattr(worker, "_load_offset", AsyncMock(return_value=0))
    store = AsyncMock()
    monkeypatch.setattr(worker, "_store_offset", store)
    monkeypatch.setattr(module, "telegram_poll_admission_open", AsyncMock(return_value=True))
    async def admitted(action, **kwargs):
        await action()
        return True
    monkeypatch.setattr(module, "run_telegram_action", admitted)
    calls = []
    async def updates(offset, timeout):
        calls.append(offset)
        if len(calls) == 1:
            raise module.TelegramWorkerError(PRIVATE_MARKER, code="telegram_read_timeout")
        if len(calls) == 3:
            worker.stop_event.set()
        return []
    worker.api.get_updates = updates
    async def immediate_wait(awaitable, timeout):
        awaitable.close()
        raise TimeoutError
    monkeypatch.setattr(module.asyncio, "wait_for", immediate_wait)
    asyncio.run(worker.run())
    assert states == ["running", "degraded", "running", "stopped"]
    assert calls == [0, 0, 0]
    store.assert_not_awaited()
    logger.warning.assert_called_once()
    health = json.loads(worker.health_path.read_text())
    assert health["errors"] == 1
    assert health["last_error_code"] == "telegram_read_timeout"
    assert module.healthcheck(worker.health_path) == 1  # A stopped process is not healthy.
