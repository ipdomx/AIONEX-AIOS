"""Actual Telegram worker loops against disposable PostgreSQL; fake remote API.

No live Telegram token, message, provider, customer input, or production row.
Only the command callback is replaced in loop tests; offset writes and locks
are real. Independent existing suites retain handler authentication coverage.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models import AuditEvent, OwnerControlRecord
from app.services import host_maintenance_admission as maintenance
from app.services import telegram_worker as owner_worker
from app.services import user_telegram_worker as user_worker
from tests.test_fr06d10a_media_claim_fence import _open
from tests.test_fr06d10a_media_claim_fence import case as case


def _fence():
    try:
        return importlib.import_module("app.services.host_maintenance_telegram")
    except ModuleNotFoundError as exc:
        if exc.name != "app.services.host_maintenance_telegram":
            raise
        return None


async def _state(case, value):
    if value == "closed":
        return
    async with case.sessions() as session, session.begin():
        row = await session.get(OwnerControlRecord, case.authority_id)
        if value == "missing":
            await session.delete(row)
        elif value == "malformed":
            row.payload = {"unexpected": True}
        elif value == "schema7":
            row.status, row.enabled = "open", True
            row.payload = {**row.payload, "schema_version": 7,
                           "scope": maintenance.STUDIO_REQUEST_COVERAGE_SCOPE}
        else:
            raise AssertionError(value)
    case.sql.clear()


def _worker(case, monkeypatch, tmp_path, kind, *, close_after_poll=False):
    module = owner_worker if kind == "owner" else user_worker
    monkeypatch.setattr(module, "SessionLocal", case.sessions)
    fence = _fence()
    if fence is not None:
        monkeypatch.setattr(fence, "SessionLocal", case.sessions)
    calls, handled = [], []
    worker = None

    async def poll(offset, timeout):
        calls.append(("poll", offset))
        if close_after_poll:
            await maintenance.close_admission(operation_id=case.operation,
                expected_generation=26, reason="Synthetic closure after remote poll",
                session_factory=case.sessions)
        return [{"update_id": 42, "message": {"from": {"id": 123456},
                "chat": {"id": 123456, "type": "private"}, "text": "/help"}}]

    async def call(method, payload):
        calls.append((method, payload))
        return {"result": {"id": 654321, "username": "synthetic_bot"}}

    api = SimpleNamespace(get_updates=poll, _call=call)
    worker = (module.TelegramOperationsWorker if kind == "owner" else module.UserTelegramWorker)(api)
    if kind == "owner":
        worker.health_path = tmp_path / "owner.json"
    else:
        worker.health_path = tmp_path / "user.json"
    original_health = worker._write_health
    health_count = 0

    def health(status, *, offset):
        nonlocal health_count
        original_health(status, offset=offset)
        health_count += 1
        if health_count >= 2:
            worker.stop_event.set()

    async def handle(message):
        handled.append(message.update_id)
        async with case.sessions() as session, session.begin():
            session.add(AuditEvent(action="synthetic.telegram.command",
                resource_type="test", resource_id=str(message.update_id), details={}))

    monkeypatch.setattr(worker, "_write_health", health)
    monkeypatch.setattr(worker, "_handle", handle)
    return worker, calls, handled, module


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
@pytest.mark.parametrize("state", ["closed", "missing", "malformed", "schema7"])
async def test_closed_or_unavailable_loop_performs_no_remote_call_or_payload_write(case, monkeypatch, tmp_path, kind, state):
    await _state(case, state)
    worker, calls, handled, _ = _worker(case, monkeypatch, tmp_path, kind)
    await worker.run()
    assert calls == []
    assert handled == []
    assert not any(q.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in case.sql)
    assert worker.last_update_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
async def test_open_loop_preserves_real_offset_and_command_audit(case, monkeypatch, tmp_path, kind):
    await _open(case)
    worker, calls, handled, module = _worker(case, monkeypatch, tmp_path, kind)
    await worker.run()
    assert handled == [42]
    assert ("poll", 0) in calls
    assert worker.last_update_id == 42
    async with case.sessions() as session:
        row = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == module._OFFSET_DOMAIN,
            OwnerControlRecord.resource_id == module._OFFSET_RESOURCE))
        assert row.payload["next_update_id"] == 43
        audit = list((await session.scalars(select(AuditEvent).where(
            AuditEvent.action == "synthetic.telegram.command"))).all())
        assert len(audit) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
async def test_close_after_poll_preserves_unprocessed_update_without_ack_offset(case, monkeypatch, tmp_path, kind):
    await _open(case)
    worker, _, handled, module = _worker(case, monkeypatch, tmp_path, kind, close_after_poll=True)
    await worker.run()
    assert handled == []
    assert worker.last_update_id is None
    async with case.sessions() as session:
        row = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == module._OFFSET_DOMAIN,
            OwnerControlRecord.resource_id == module._OFFSET_RESOURCE))
        assert row is None
        authority = await session.get(OwnerControlRecord, case.authority_id)
        assert authority.status == "closed" and authority.version == 27


async def _guard(case, monkeypatch):
    module = _fence()
    assert module is not None
    monkeypatch.setattr(module, "SessionLocal", case.sessions)
    return module


async def _close(case):
    return await maintenance.close_admission(operation_id=case.operation,
        expected_generation=26, reason="Synthetic Telegram transition",
        session_factory=case.sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
@pytest.mark.parametrize("outcome", ["commit", "rollback"])
async def test_action_lock_outlives_inner_transaction_and_reply(case, monkeypatch, kind, outcome):
    import asyncio
    from sqlalchemy import text
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock

    await _open(case)
    module = await _guard(case, monkeypatch)
    entered, finish = asyncio.Event(), asyncio.Event()
    original = module._open
    holder = {}

    async def observed(session):
        accepted = await original(session)
        holder["pid"] = await session.scalar(text("SELECT pg_backend_pid()"))
        return accepted

    monkeypatch.setattr(module, "_open", observed)
    identity = str(uuid4())

    async def action():
        async with case.sessions() as session:
            session.add(OwnerControlRecord(id=identity, domain="synthetic-telegram",
                resource_id=identity, payload={}))
            await session.flush()
            await getattr(session, outcome)()
        entered.set()
        await finish.wait()

    task = asyncio.create_task(module.run_telegram_action(action, consumer=kind))
    close = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        close = asyncio.create_task(_close(case))
        await _wait_for_lock(case, holder["pid"])
        assert not close.done()
        finish.set()
        assert await asyncio.wait_for(task, 3) is True
        assert (await asyncio.wait_for(close, 3)).generation == 27
        async with case.sessions() as session:
            assert (await session.get(OwnerControlRecord, identity) is not None) is (outcome == "commit")
    finally:
        finish.set()
        await asyncio.gather(task, *([close] if close else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
async def test_closer_first_refuses_action_after_real_lock_wait(case, monkeypatch, kind):
    import asyncio
    from sqlalchemy import text
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock

    await _open(case)
    module = await _guard(case, monkeypatch)
    effects = []

    async def action():
        effects.append(True)

    task = None
    async with case.sessions() as closer:
        try:
            row = await closer.scalar(select(OwnerControlRecord).where(
                OwnerControlRecord.id == case.authority_id).with_for_update())
            pid = await closer.scalar(text("SELECT pg_backend_pid()"))
            row.status, row.enabled = "closed", False
            await closer.flush()
            task = asyncio.create_task(module.run_telegram_action(action, consumer=kind))
            await _wait_for_lock(case, pid)
            assert not task.done() and effects == []
            await closer.commit()
            assert await asyncio.wait_for(task, 3) is False
            assert effects == []
        finally:
            await closer.rollback()
            if task is not None:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_repeated_cancellation_retains_guard_until_started_thread_finishes(case, monkeypatch, tmp_path, fail):
    import asyncio
    import threading
    from sqlalchemy import text
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock

    await _open(case)
    module = await _guard(case, monkeypatch)
    entered, finish = threading.Event(), threading.Event()
    holder, calls = {}, []
    original = module._open
    result = tmp_path / "synthetic-completion.txt"

    async def observed(session):
        accepted = await original(session)
        holder["pid"] = await session.scalar(text("SELECT pg_backend_pid()"))
        return accepted

    monkeypatch.setattr(module, "_open", observed)

    def effect():
        calls.append(True)
        entered.set()
        assert finish.wait(5)
        result.write_text("owned action finished")
        if fail:
            raise RuntimeError("Synthetic action failure after effect")

    async def action():
        await asyncio.to_thread(effect)

    task = asyncio.create_task(module.run_telegram_action(action, consumer="owner"))
    close = None
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(.01)
        assert entered.is_set()
        close = asyncio.create_task(_close(case))
        await _wait_for_lock(case, holder["pid"])
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(.02)
        assert not task.done() and not close.done() and not result.exists()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert (await asyncio.wait_for(close, 3)).generation == 27
        assert calls == [True] and result.read_text() == "owned action finished"
        assert not [t for t in asyncio.all_tasks() if t.get_name() == "aionex-maintenance-bound-telegram" and not t.done()]
    finally:
        finish.set()
        await asyncio.gather(task, *([close] if close else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancellation_before_admission_never_constructs_action(case, monkeypatch):
    import asyncio
    from sqlalchemy import text
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock

    await _open(case)
    module = await _guard(case, monkeypatch)
    calls = []

    def action():
        calls.append(True)
        raise AssertionError("Action factory must not run")

    async with case.sessions() as closer:
        await maintenance._locked_snapshot(closer, exclusive=True)
        pid = await closer.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(module.run_telegram_action(action, consumer="user"))
        try:
            await _wait_for_lock(case, pid)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
            assert calls == []
        finally:
            await closer.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cached_open_authority_cannot_admit_after_durable_close(case, monkeypatch):
    await _open(case)
    module = await _guard(case, monkeypatch)
    async with case.sessions() as stale:
        held = await stale.get(OwnerControlRecord, case.authority_id)
        assert held.status == "open"
        await _close(case)
        assert await module._open(stale) is False
        await stale.rollback()


@pytest.mark.asyncio
async def test_failed_readonly_lock_is_denied_without_autoflush(case, monkeypatch):
    from sqlalchemy import text
    await _open(case)
    module = await _guard(case, monkeypatch)
    async with case.sessions() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        pending = OwnerControlRecord(domain="unflushed-synthetic", resource_id=uuid4().hex, payload={})
        session.add(pending)
        case.sql.clear()
        assert await module._open(session) is False
        assert pending in session.new
        assert not any(q.lstrip().upper().startswith("INSERT") for q in case.sql)
        await session.rollback()


@pytest.mark.asyncio
async def test_programming_error_and_unknown_consumer_are_not_silent_denial(case, monkeypatch):
    await _open(case)
    module = await _guard(case, monkeypatch)
    calls = []

    async def broken():
        calls.append(True)
        raise ValueError("Synthetic programming error")

    with pytest.raises(ValueError, match="Unknown"):
        await module.run_telegram_action(broken, consumer="misspelled")
    assert calls == []
    with pytest.raises(ValueError, match="Synthetic"):
        await module.run_telegram_action(broken, consumer="owner")
    assert calls == [True]
    assert (await _close(case)).generation == 27


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
async def test_offset_failure_cannot_advance_memory_or_last_processed_id(case, monkeypatch, tmp_path, kind):
    import json
    await _open(case)
    worker, _, handled, _ = _worker(case, monkeypatch, tmp_path, kind)

    async def fail(offset):
        raise owner_worker.TelegramWorkerError("Synthetic offset commit failure")

    monkeypatch.setattr(worker, "_store_offset", fail)
    await worker.run()
    assert handled == [42]
    assert worker.last_update_id is None
    assert json.loads(worker.health_path.read_text())["next_update_id"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
async def test_duplicate_or_older_polled_entries_do_not_execute_again(case, monkeypatch, tmp_path, kind):
    await _open(case)
    worker, _, handled, _ = _worker(case, monkeypatch, tmp_path, kind)
    original = worker.api.get_updates

    async def repeated(offset, timeout):
        row = (await original(offset, timeout))[0]
        return [row, row, {**row, "update_id": 41}]

    worker.api.get_updates = repeated
    await worker.run()
    assert handled == [42] and worker.last_update_id == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
async def test_stop_finishes_current_update_but_does_not_start_next(case, monkeypatch, tmp_path, kind):
    await _open(case)
    worker, _, handled, module = _worker(case, monkeypatch, tmp_path, kind)
    original_poll, original_handle = worker.api.get_updates, worker._handle

    async def poll(offset, timeout):
        row = (await original_poll(offset, timeout))[0]
        return [row, {**row, "update_id": 43}]

    async def handle(message):
        await original_handle(message)
        worker.stop_event.set()

    worker.api.get_updates = poll
    monkeypatch.setattr(worker, "_handle", handle)
    await worker.run()
    assert handled == [42]
    async with case.sessions() as session:
        row = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == module._OFFSET_DOMAIN,
            OwnerControlRecord.resource_id == module._OFFSET_RESOURCE))
        assert row.payload["next_update_id"] == 43


def test_guard_engine_is_not_the_business_connection_pool():
    from app.db.base import SessionLocal as business
    module = _fence()
    assert module is not None
    assert module.SessionLocal.kw["bind"] is not business.kw["bind"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
async def test_real_handler_reply_and_audit_remain_inside_admitted_batch(case, monkeypatch, tmp_path, kind):
    await _open(case)
    worker, calls, _, module = _worker(case, monkeypatch, tmp_path, kind)
    original_poll = worker.api.get_updates
    worker_type = module.TelegramOperationsWorker if kind == "owner" else module.UserTelegramWorker
    # Restore the unmodified real handler. Non-private requests are rejected by
    # its original security boundary, with a real audit and durable offset.
    monkeypatch.setattr(worker, "_handle", worker_type._handle.__get__(worker, worker_type))

    async def poll(offset, timeout):
        rows = await original_poll(offset, timeout)
        rows[0]["message"]["chat"]["type"] = "group"
        return rows

    async def send(chat_id, text):
        calls.append(("reply", chat_id))
        assert text

    worker.api.get_updates, worker.api.send_message = poll, send
    await worker.run()
    assert ("reply", 123456) in calls
    action = "telegram.command" if kind == "owner" else "telegram.user_command"
    async with case.sessions() as session:
        audits = list((await session.scalars(select(AuditEvent).where(AuditEvent.action == action))).all())
        assert len(audits) == 1
        assert audits[0].details["reason"] == "non-private-chat"
        assert audits[0].details["status"] == "rejected"
        row = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == module._OFFSET_DOMAIN,
            OwnerControlRecord.resource_id == module._OFFSET_RESOURCE))
        assert row.payload["next_update_id"] == 43


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["owner", "user"])
async def test_later_batch_failure_retains_only_previously_committed_offset(case, monkeypatch, tmp_path, kind):
    import json
    await _open(case)
    worker, _, handled, module = _worker(case, monkeypatch, tmp_path, kind)
    original_poll, original_handle = worker.api.get_updates, worker._handle

    async def poll(offset, timeout):
        row = (await original_poll(offset, timeout))[0]
        return [row, {**row, "update_id": 43}]

    async def handle(message):
        if message.update_id == 43:
            raise owner_worker.TelegramWorkerError("Synthetic second-command error")
        await original_handle(message)

    worker.api.get_updates = poll
    monkeypatch.setattr(worker, "_handle", handle)
    await worker.run()
    assert handled == [42] and worker.last_update_id == 42
    assert json.loads(worker.health_path.read_text())["next_update_id"] == 43
    async with case.sessions() as session:
        row = await session.scalar(select(OwnerControlRecord).where(
            OwnerControlRecord.domain == module._OFFSET_DOMAIN,
            OwnerControlRecord.resource_id == module._OFFSET_RESOURCE))
        assert row.payload["next_update_id"] == 43
