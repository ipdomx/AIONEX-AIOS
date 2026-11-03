"""Long-poll noise contracts for the Telegram workers (roadmap Phase 0 item 0.2).

Offline only: no credentials, external requests or database writes.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.core.config import settings
from app.services import telegram_worker as module
from app.services import user_telegram_worker as user_module

TOKEN_SHAPE = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghi"


@pytest.mark.parametrize("poll_seconds", [5, 25, 50])
def test_long_poll_read_timeout_exceeds_get_updates_timeout(poll_seconds):
    assert module.long_poll_read_timeout(poll_seconds) >= poll_seconds + 10


def test_get_updates_uses_read_timeout_longer_than_long_poll():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({
            "timeout": request.extensions.get("timeout"),
            "body": json.loads(request.content),
        })
        return httpx.Response(200, json={"ok": True, "result": []})

    async def exercise():
        api = module.TelegramBotAPI(TOKEN_SHAPE)
        await api._client.aclose()
        api._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await api.get_updates(0, 50)
        finally:
            await api.close()

    assert asyncio.run(exercise()) == []
    assert len(seen) == 1
    assert seen[0]["body"]["timeout"] == 50
    assert seen[0]["timeout"]["read"] > 50


def test_poll_backoff_is_exponential_jittered_and_capped():
    assert module.poll_backoff_seconds(1, jitter=1.0) == 1.0
    assert module.poll_backoff_seconds(1, jitter=0.0) == 0.5
    assert module.poll_backoff_seconds(2, jitter=1.0) == 2.0
    assert module.poll_backoff_seconds(4, jitter=1.0) == 8.0
    assert module.poll_backoff_seconds(40, jitter=1.0) == 60.0
    for _ in range(50):
        value = module.poll_backoff_seconds(3)
        assert 2.0 <= value <= 4.0


def _owner_worker(monkeypatch, tmp_path: Path, outcomes):
    monkeypatch.setattr(settings, "AIOS_TELEGRAM_HEALTH_FILE", str(tmp_path / "health.json"))
    monkeypatch.setattr(settings, "AIOS_TELEGRAM_ALLOWED_USERS", [1001])
    logger = Mock()
    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(module.random, "random", lambda: 1.0)
    worker = module.TelegramOperationsWorker(Mock())
    states: list[str] = []
    write_health = worker._write_health

    def capture(status, *, offset):
        states.append(status)
        write_health(status, offset=offset)

    monkeypatch.setattr(worker, "_write_health", capture)
    monkeypatch.setattr(worker, "_load_offset", AsyncMock(return_value=0))
    monkeypatch.setattr(worker, "_store_offset", AsyncMock())
    monkeypatch.setattr(module, "telegram_poll_admission_open", AsyncMock(return_value=True))

    async def admitted(action, **kwargs):
        await action()
        return True

    monkeypatch.setattr(module, "run_telegram_action", admitted)
    pending = list(outcomes)
    calls: list[int] = []

    async def updates(offset, timeout):
        calls.append(offset)
        outcome = pending.pop(0)
        if not pending:
            worker.stop_event.set()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    worker.api.get_updates = updates
    waits: list[float] = []

    async def immediate_wait(awaitable, timeout):
        awaitable.close()
        waits.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(module.asyncio, "wait_for", immediate_wait)
    return worker, logger, states, calls, waits


def _read_timeout():
    return module.TelegramWorkerError("read timeout", code="telegram_read_timeout")


def _bad_gateway():
    return module.TelegramWorkerError(
        "Telegram API returned HTTP 502", code="telegram_http_error", http_status=502,
    )


def test_long_poll_read_timeouts_are_quiet_and_uncounted(monkeypatch, tmp_path):
    worker, logger, states, calls, waits = _owner_worker(
        monkeypatch, tmp_path, [_read_timeout(), _read_timeout(), _read_timeout(), []],
    )
    asyncio.run(worker.run())
    assert len(calls) == 4
    assert "degraded" not in states
    assert waits == []  # Polling resumes immediately, no backoff.
    assert worker.errors == 0 and worker.consecutive_failures == 0
    logger.warning.assert_not_called()
    logger.debug.assert_any_call(
        "Telegram long poll read timeout", error_code="telegram_read_timeout",
    )
    health = json.loads(worker.health_path.read_text())
    assert health["errors"] == 0 and health["last_error_code"] is None


def test_read_timeout_outside_long_poll_is_still_a_failure(monkeypatch, tmp_path):
    worker, logger, states, calls, waits = _owner_worker(
        monkeypatch, tmp_path, [[{"update_id": 7}], []],
    )

    async def consume_fails(action, **kwargs):
        if len(calls) == 1:
            raise _read_timeout()
        await action()
        return True

    monkeypatch.setattr(module, "run_telegram_action", consume_fails)
    asyncio.run(worker.run())
    assert worker.errors == 1
    assert "degraded" in states
    assert waits == [1.0]


def test_transient_failures_back_off_and_warn_only_after_threshold(monkeypatch, tmp_path):
    threshold = module.POLL_FAILURE_WARNING_THRESHOLD
    failures = [_bad_gateway() for _ in range(threshold + 1)]
    worker, logger, states, calls, waits = _owner_worker(
        monkeypatch, tmp_path, [*failures, [], []],
    )
    asyncio.run(worker.run())
    # Exponential backoff with (pinned) jitter between consecutive failures.
    assert waits == [module.poll_backoff_seconds(n, jitter=1.0) for n in range(1, threshold + 2)]
    assert waits == sorted(waits) and waits[0] < waits[-1]
    assert logger.debug.call_count >= threshold - 1
    warned = [c for c in logger.warning.call_args_list if c.args[0] == "Telegram polling failure"]
    assert len(warned) == 2  # Failures #threshold and #threshold+1 only.
    assert warned[0].kwargs["consecutive_failures"] == threshold
    logger.info.assert_any_call("Telegram polling recovered", consecutive_failures=threshold + 1)
    assert worker.consecutive_failures == 0
    assert worker.errors == threshold + 1


def test_connect_timeouts_and_network_errors_use_backoff(monkeypatch, tmp_path):
    worker, logger, states, calls, waits = _owner_worker(monkeypatch, tmp_path, [
        module.TelegramWorkerError("x", code="telegram_connect_timeout"),
        module.TelegramWorkerError("x", code="telegram_network_error"),
        [],
    ])
    asyncio.run(worker.run())
    assert waits == [1.0, 2.0]
    logger.warning.assert_not_called()
    assert worker.errors == 2


def test_user_worker_long_poll_read_timeout_is_quiet(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "AIOS_USER_TELEGRAM_HEALTH_FILE", str(tmp_path / "user.json"))
    logger = Mock()
    monkeypatch.setattr(user_module, "logger", logger)
    worker = user_module.UserTelegramWorker(Mock())
    monkeypatch.setattr(worker, "_load_offset", AsyncMock(return_value=0))
    monkeypatch.setattr(worker, "_store_offset", AsyncMock())
    monkeypatch.setattr(worker, "_record_bot_identity", AsyncMock())
    monkeypatch.setattr(user_module, "telegram_poll_admission_open", AsyncMock(return_value=True))

    async def admitted(action, **kwargs):
        await action()
        return True

    monkeypatch.setattr(user_module, "run_telegram_action", admitted)
    sleeps: list[float] = []

    async def no_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(user_module.asyncio, "sleep", no_sleep)
    pending = [_read_timeout(), _read_timeout(), _bad_gateway(), []]

    async def updates(offset, timeout):
        outcome = pending.pop(0)
        if not pending:
            worker.stop_event.set()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    worker.api.get_updates = updates
    asyncio.run(worker.run())
    assert len(sleeps) == 1  # Only the 502 backs off.
    logger.warning.assert_not_called()
    logger.debug.assert_any_call("User Telegram long poll read timeout")
