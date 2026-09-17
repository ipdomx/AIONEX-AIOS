"""Real PostgreSQL notification execution with synthetic provider boundaries.

The imported fixture creates a private UUID schema on an explicitly disposable
database. Claim, capability consumption, input preparation, heartbeat, result
transactions, uncertainty marking, finish, and worker polling stay real.
Only provider clients/configuration are synthetic; no external service is used.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    CommunicationEndpoint,
    HostMaintenanceWorkCycle,
    NotificationDelivery,
    NotificationDeliveryAttempt,
)
from app.services import communication_worker as worker
from app.services import communications
from app.services import host_maintenance_admission as admission
from app.services import host_maintenance_notifications as activities
from tests.test_host_maintenance_notifications_db import (
    notification_db as notification_db,
)


WAIT_SECONDS = 15
HEARTBEAT_INTERVAL = 0.05


def _forbidden_provider(*_args, **_kwargs):
    raise AssertionError("An unconfigured synthetic provider boundary was reached")


@pytest_asyncio.fixture
async def runtime_case(notification_db, monkeypatch, tmp_path):
    firebase_file = tmp_path / "synthetic-firebase.json"
    firebase_file.write_text(
        json.dumps(
            {
                "type": "service_account",
                "project_id": "synthetic-project",
                "client_email": "synthetic@example.test",
                "private_key": "synthetic-unused-key",
            }
        ),
        encoding="utf-8",
    )
    telegram_file = tmp_path / "synthetic-telegram-token"
    telegram_file.write_text("123456789:" + "A" * 32, encoding="utf-8")
    telegram_file.chmod(0o600)
    for name, value in {
        "SECRET_KEY": "synthetic-notification-runtime-encryption-key",
        "SMTP_HOST": "smtp.example.test",
        "SMTP_PORT": 465,
        "SMTP_SSL": True,
        "SMTP_TLS": False,
        "SMTP_USER": None,
        "SMTP_PASSWORD": None,
        "SMTP_FROM_EMAIL": "sender@example.test",
        "FIREBASE_PROJECT_ID": "synthetic-project",
        "FIREBASE_ADMIN_CREDENTIALS_JSON": str(firebase_file),
        "AIOS_TELEGRAM_BOT_TOKEN_FILE": str(telegram_file),
        "AIOS_USER_TELEGRAM_BOT_TOKEN_FILE": str(telegram_file),
        "WHATSAPP_API_BASE": "https://graph.example.test/v1",
        "WHATSAPP_PHONE_NUMBER_ID": "123456",
        "WHATSAPP_ACCESS_TOKEN": "synthetic-provider-token",
        "COMMUNICATION_WORKER_HEALTH_FILE": str(tmp_path / "worker-health.json"),
    }.items():
        monkeypatch.setattr(communications.settings, name, value)

    monkeypatch.setattr(communications.smtplib, "SMTP", _forbidden_provider)
    monkeypatch.setattr(communications.smtplib, "SMTP_SSL", _forbidden_provider)
    monkeypatch.setattr(communications, "TelegramBotAPI", _forbidden_provider)
    monkeypatch.setattr(communications.httpx, "AsyncClient", _forbidden_provider)
    monkeypatch.setattr(communications, "_firebase_app", None)
    sdk = ModuleType("firebase_admin")
    credentials = ModuleType("firebase_admin.credentials")
    messaging = ModuleType("firebase_admin.messaging")
    sdk.credentials = credentials
    sdk.messaging = messaging
    sdk.get_app = _forbidden_provider
    sdk.initialize_app = _forbidden_provider
    credentials.Certificate = _forbidden_provider
    messaging.Message = SimpleNamespace
    messaging.Notification = SimpleNamespace
    messaging.send = _forbidden_provider
    for name, module in (
        ("firebase_admin", sdk),
        ("firebase_admin.credentials", credentials),
        ("firebase_admin.messaging", messaging),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    case = SimpleNamespace(
        db=notification_db,
        sessions=notification_db.sessions,
        loop=asyncio.get_running_loop(),
        loop_thread=threading.get_ident(),
        tmp_path=tmp_path,
        target_id=None,
        provider=None,
        before_send=[],
        sdk=sdk,
        messaging=messaging,
    )
    try:
        yield case
    finally:
        if case.provider is not None:
            case.provider.release()


async def _new_delivery(case, channel="email", *, priority=50):
    address = {
        "email": "recipient@example.test",
        "push": "synthetic-device-address",
        "telegram": "123",
        "whatsapp": "971501234567",
    }[channel]
    async with case.sessions() as session:
        endpoint = await session.scalar(
            select(CommunicationEndpoint).where(
                CommunicationEndpoint.user_id == case.db.user_ids[0],
                CommunicationEndpoint.channel == channel,
                CommunicationEndpoint.address_hash
                == communications.address_hash(address),
            )
        )
        if endpoint is None:
            endpoint = CommunicationEndpoint(
                id=str(uuid4()),
                organization_id=case.db.organization_ids[0],
                user_id=case.db.user_ids[0],
                channel=channel,
                address_ciphertext=communications.encrypt_address(address),
                address_hash=communications.address_hash(address),
                label="Synthetic runtime recipient",
                status="active",
                verified_at=datetime.now(UTC),
                endpoint_metadata=(
                    {"bot_scope": "owner"} if channel == "telegram" else {}
                ),
            )
            session.add(endpoint)
        await session.commit()
        endpoint_id = endpoint.id
    return await case.db.new_delivery(
        channel=channel, endpoint_id=endpoint_id, priority=priority
    )


async def _claim(case):
    async with case.sessions() as session:
        return await communications.claim_due_deliveries(
            session, worker_incarnation=str(uuid4()), limit=1
        )


async def _owned_delivery(case, channel="email"):
    case.target_id = await _new_delivery(case, channel)
    claimed = await _claim(case)
    assert len(claimed) == 1 and claimed[0].delivery_id == case.target_id
    return claimed[0]


async def _process(case, ownership):
    return await communications.process_delivery(
        ownership,
        session_factory=case.sessions,
        dispatcher=None,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
    )


async def _observe_committed_before_send(case):
    # This independent connection executes from the provider boundary before the
    # synthetic sender records acceptance or waits on its execution barrier.
    async with case.sessions() as observer:
        delivery = await observer.get(NotificationDelivery, case.target_id)
        owners = (
            await observer.scalars(
                select(HostMaintenanceWorkCycle).where(
                    HostMaintenanceWorkCycle.consumer == activities.CONSUMER,
                    HostMaintenanceWorkCycle.job_id == case.target_id,
                )
            )
        ).all()
        assert delivery is not None and delivery.status == "processing"
        assert delivery.attempt_count == 1
        assert len(owners) == 1
        owner = owners[0]
        attempt = await observer.get(NotificationDeliveryAttempt, owner.id)
        assert owner.state == "active" and owner.phase == "dispatching"
        assert attempt is not None and attempt.delivery_id == case.target_id
        assert attempt.status == "started" and attempt.attempt_number == 1
        assert attempt.dispatch_protocol_version == 1
        assert attempt.dispatch_outcome is None and attempt.completed_at is None
        case.before_send.append((owner.id, owner.admitted_generation))


class ThreadProvider:
    def __init__(self, case, channel):
        self.case = case
        self.channel = channel
        self.send_entered = threading.Event()
        self.send_release = threading.Event()
        self.cleanup_entered = threading.Event()
        self.cleanup_release = threading.Event()
        self.finished = threading.Event()
        self.send_release.set()
        self.cleanup_release.set()
        self.calls = []
        self.closes = 0

    def send(self, message):
        assert threading.get_ident() != self.case.loop_thread
        observed = asyncio.run_coroutine_threadsafe(
            _observe_committed_before_send(self.case), self.case.loop
        )
        observed.result(timeout=WAIT_SECONDS)
        self.calls.append(message)
        self.send_entered.set()
        if not self.send_release.wait(WAIT_SECONDS):
            raise RuntimeError("Synthetic provider send barrier timed out")

    def cleanup(self):
        self.cleanup_entered.set()
        try:
            if not self.cleanup_release.wait(WAIT_SECONDS):
                raise RuntimeError("Synthetic provider cleanup barrier timed out")
            self.closes += 1
        finally:
            self.finished.set()

    def release(self):
        self.send_release.set()
        self.cleanup_release.set()


def _thread_provider(case, monkeypatch, channel):
    provider = ThreadProvider(case, channel)
    case.provider = provider
    if channel == "email":

        class SMTP:
            def __enter__(self):
                return self

            def __exit__(self, *_exception):
                provider.cleanup()
                return False

            def ehlo(self):
                return None

            def send_message(self, message):
                assert message["To"] == "recipient@example.test"
                provider.send(message)
                return {}

        monkeypatch.setattr(
            communications.smtplib, "SMTP_SSL", lambda *_args, **_kwargs: SMTP()
        )
    else:
        assert channel == "push"
        app = SimpleNamespace(name="synthetic-firebase-app")
        monkeypatch.setattr(case.sdk, "get_app", lambda _name: app)

        def send(message, *, app):
            assert app.name == "synthetic-firebase-app"
            assert message.token == "synthetic-device-address"
            try:
                provider.send(message)
                return "synthetic-push-acknowledgement"
            finally:
                # The synthetic SDK owns this finalization before its send
                # call returns to the actual _send_push thread wrapper.
                provider.cleanup()

        monkeypatch.setattr(case.messaging, "send", send)
    return provider


class AsyncProvider:
    def __init__(self, case, channel):
        self.case = case
        self.channel = channel
        self.send_entered = asyncio.Event()
        self.cleanup_entered = asyncio.Event()
        self.cleanup_release = asyncio.Event()
        self.finished = asyncio.Event()
        self.close_cancelled = asyncio.Event()
        self.cleanup_release.set()
        self.calls = []
        self.closes = 0
        self.fail_close = False

    async def send(self, request):
        await _observe_committed_before_send(self.case)
        self.calls.append(request)
        self.send_entered.set()

    async def close(self):
        self.cleanup_entered.set()
        try:
            await self.cleanup_release.wait()
            self.closes += 1
            if self.fail_close:
                raise RuntimeError("Synthetic provider client close failed")
        except asyncio.CancelledError:
            self.close_cancelled.set()
            raise
        finally:
            self.finished.set()

    def release(self):
        self.cleanup_release.set()


def _async_provider(case, monkeypatch, channel):
    provider = AsyncProvider(case, channel)
    case.provider = provider
    if channel == "telegram":

        class Telegram:
            async def send_message_response(self, chat_id, message):
                assert chat_id == 123
                await provider.send((chat_id, message))
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "result": {
                            "message_id": 77,
                            "chat": {"id": chat_id},
                            "date": 1789640000,
                        },
                    },
                )

            async def close(self):
                await provider.close()

        monkeypatch.setattr(communications, "TelegramBotAPI", lambda _token: Telegram())
    else:
        assert channel == "whatsapp"

        class Client:
            async def post(self, url, *, headers, json):
                assert url == "https://graph.example.test/v1/123456/messages"
                assert json["to"] == "971501234567"
                await provider.send((url, json))
                return httpx.Response(
                    200,
                    json={"messages": [{"id": "synthetic-whatsapp-acknowledgement"}]},
                )

            async def aclose(self):
                await provider.close()

        monkeypatch.setattr(
            communications.httpx, "AsyncClient", lambda **_kwargs: Client()
        )
    return provider


async def _wait_thread(event):
    async with asyncio.timeout(WAIT_SECONDS):
        while not event.is_set():
            await asyncio.sleep(0.005)


async def _wait_async(event):
    await asyncio.wait_for(event.wait(), timeout=WAIT_SECONDS)


async def _drain(task):
    if task is not None:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(
            asyncio.gather(task, return_exceptions=True), timeout=WAIT_SECONDS
        )


async def _closed_snapshot(case, closed, *, unresolved=False):
    snapshot = await case.db.snapshot(closed)
    assert snapshot.authority.operation_id == closed.operation_id
    assert snapshot.authority.generation == closed.generation
    assert not snapshot.authority.is_open
    assert snapshot.blocker_count == 1 and snapshot.unfinished_count == 1
    assert not snapshot.is_clear
    assert snapshot.unresolved_count == int(unresolved)
    return snapshot


async def _wait_unresolved(case):
    async with asyncio.timeout(WAIT_SECONDS):
        while True:
            rows = await case.db.registry_rows()
            if len(rows) == 1 and rows[0]["state"] == "unresolved":
                assert rows[0]["unresolved_reason"]
                return rows[0]
            await asyncio.sleep(0.005)


async def _assert_uncertain(case):
    owners = await case.db.registry_rows()
    attempts = await case.db.attempt_rows()
    delivery = await case.db.delivery_row(case.target_id)
    assert len(owners) == len(attempts) == 1
    assert owners[0]["state"] == "unresolved" and owners[0]["unresolved_reason"]
    assert owners[0]["id"] == attempts[0]["id"]
    assert attempts[0]["status"] == "uncertain"
    assert attempts[0]["dispatch_outcome"] == "uncertain"
    assert attempts[0]["completed_at"] is None
    assert attempts[0]["provider_message_id"] is None
    assert delivery["status"] == "processing" and delivery["attempt_count"] == 1
    assert delivery["provider_message_id"] is None
    return owners, attempts, delivery


async def _reopen(case, closed):
    await admission.open_admission(
        operation_id=closed.operation_id,
        expected_generation=closed.generation,
        reason="Synthetic notification runtime reopen",
        session_factory=case.sessions,
    )


async def _assert_no_resend(case, ownership, *, closed=None):
    if closed is not None:
        await _reopen(case, closed)
    calls = len(case.provider.calls)
    before = await _assert_uncertain(case)
    assert await _claim(case) == []
    assert await _claim(case) == []
    with pytest.raises(activities.NotificationActivityOwnershipLost):
        await _process(case, ownership)
    assert len(case.provider.calls) == calls
    assert await _assert_uncertain(case) == before


async def _assert_delivered(case):
    delivery = await case.db.delivery_row(case.target_id)
    attempts = await case.db.attempt_rows()
    assert await case.db.registry_rows() == []
    assert delivery["status"] == "delivered" and delivery["attempt_count"] == 1
    assert delivery["provider_message_id"]
    assert len(attempts) == 1
    assert attempts[0]["status"] == "delivered"
    assert attempts[0]["dispatch_outcome"] == "accepted"
    assert attempts[0]["completed_at"] is not None
    assert len(case.provider.calls) == len(case.before_send) == 1


async def _reject_commit(case, phase):
    # These are real deferred PostgreSQL constraint failures, never injected
    # session exceptions. Their predicates permit the later uncertainty commit.
    if phase == "claim":
        table, event = "host_maintenance_work_cycles", "INSERT"
        predicate = "NEW.consumer = '" + activities.CONSUMER + "'"
    elif phase == "begin":
        table, event = "host_maintenance_work_cycles", "UPDATE"
        predicate = (
            "NEW.phase = 'dispatching' AND OLD.phase = 'claimed' "
            "AND NEW.state = 'active'"
        )
    else:
        assert phase == "result"
        table, event = "notification_delivery_attempts", "UPDATE"
        predicate = (
            "NEW.dispatch_outcome = 'accepted' "
            "AND OLD.dispatch_outcome IS NULL"
        )
    async with case.sessions() as session:
        await session.execute(
            text(
                """
                CREATE FUNCTION reject_notification_runtime_commit()
                RETURNS trigger LANGUAGE plpgsql AS $function$
                BEGIN
                    RAISE EXCEPTION USING
                        ERRCODE = '23514',
                        MESSAGE = 'synthetic notification deferred commit rejected';
                    RETURN NEW;
                END;
                $function$
                """
            )
        )
        await session.execute(
            text(
                "CREATE CONSTRAINT TRIGGER reject_notification_runtime_commit "
                f"AFTER {event} ON {table} DEFERRABLE INITIALLY DEFERRED "
                f"FOR EACH ROW WHEN ({predicate}) "
                "EXECUTE FUNCTION reject_notification_runtime_commit()"
            )
        )
        await session.commit()
    async with case.sessions() as observer:
        evidence = (
            await observer.execute(
                text(
                    "SELECT tgdeferrable, tginitdeferred FROM pg_trigger "
                    "WHERE tgname = 'reject_notification_runtime_commit' "
                    "AND tgrelid = CAST(:table AS regclass)"
                ),
                {"table": table},
            )
        ).one()
        assert evidence.tgdeferrable and evidence.tginitdeferred

@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["email", "push"])
async def test_real_claim_precedes_send_and_closed_snapshot_blocks_until_thread_cleanup(
    runtime_case, monkeypatch, channel
):
    case = runtime_case
    provider = _thread_provider(case, monkeypatch, channel)
    provider.send_release.clear()
    provider.cleanup_release.clear()
    ownership = await _owned_delivery(case, channel)
    task = asyncio.create_task(_process(case, ownership))
    try:
        await _wait_thread(provider.send_entered)
        assert case.before_send == [
            (ownership.activity_id, ownership.admitted_generation)
        ]
        closed = await case.db.close()
        await _closed_snapshot(case, closed)
        assert not task.done() and not provider.finished.is_set()
        provider.send_release.set()
        await _wait_thread(provider.cleanup_entered)
        await _closed_snapshot(case, closed)
        assert not task.done() and not provider.finished.is_set()
        attempts = await case.db.attempt_rows()
        assert attempts[0]["status"] == "started"
        assert attempts[0]["dispatch_outcome"] is None
        provider.cleanup_release.set()
        result = await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert result.status == "delivered"
        assert provider.finished.is_set() and provider.closes == 1
        await _assert_delivered(case)
        assert (await case.db.snapshot(closed)).is_clear
    finally:
        provider.release()
        await _drain(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["email", "push"])
async def test_repeated_cancellation_retains_real_thread_and_durable_uncertainty(
    runtime_case, monkeypatch, channel
):
    case = runtime_case
    provider = _thread_provider(case, monkeypatch, channel)
    provider.send_release.clear()
    provider.cleanup_release.clear()
    ownership = await _owned_delivery(case, channel)
    task = asyncio.create_task(_process(case, ownership))
    try:
        await _wait_thread(provider.send_entered)
        closed = await case.db.close()
        task.cancel()
        await _wait_unresolved(case)
        await _closed_snapshot(case, closed, unresolved=True)
        await _assert_uncertain(case)
        assert not task.done() and not provider.finished.is_set()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done() and not provider.finished.is_set()
        provider.send_release.set()
        await _wait_thread(provider.cleanup_entered)
        await _closed_snapshot(case, closed, unresolved=True)
        assert not task.done() and not provider.finished.is_set()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        provider.cleanup_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert provider.finished.is_set() and provider.closes == 1
        await _assert_uncertain(case)
        await _assert_no_resend(case, ownership, closed=closed)
        assert len(provider.calls) == len(case.before_send) == 1
    finally:
        provider.release()
        await _drain(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["telegram", "whatsapp"])
@pytest.mark.parametrize("outcome", ["success", "cancel", "failure"])
async def test_actual_async_adapter_keeps_activity_through_client_close(
    runtime_case, monkeypatch, channel, outcome
):
    case = runtime_case
    provider = _async_provider(case, monkeypatch, channel)
    provider.cleanup_release.clear()
    provider.fail_close = outcome == "failure"
    ownership = await _owned_delivery(case, channel)
    task = asyncio.create_task(_process(case, ownership))
    try:
        await _wait_async(provider.cleanup_entered)
        assert case.before_send == [
            (ownership.activity_id, ownership.admitted_generation)
        ]
        closed = await case.db.close()
        await _closed_snapshot(case, closed)
        assert not task.done() and not provider.finished.is_set()
        if outcome == "cancel":
            task.cancel()
            await _wait_unresolved(case)
            await _closed_snapshot(case, closed, unresolved=True)
            await _assert_uncertain(case)
            assert not task.done() and not provider.finished.is_set()
            assert not provider.close_cancelled.is_set()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not provider.finished.is_set()
            assert not provider.close_cancelled.is_set()
        provider.cleanup_release.set()
        if outcome == "success":
            result = await asyncio.wait_for(task, timeout=WAIT_SECONDS)
            assert result.status == "delivered"
            await _assert_delivered(case)
            assert (await case.db.snapshot(closed)).is_clear
        else:
            expected = (
                asyncio.CancelledError
                if outcome == "cancel"
                else communications.NotificationDispatchUncertain
            )
            with pytest.raises(expected):
                await asyncio.wait_for(task, timeout=WAIT_SECONDS)
            await _assert_uncertain(case)
            await _closed_snapshot(case, closed, unresolved=True)
            await _assert_no_resend(case, ownership, closed=closed)
        assert provider.finished.is_set() and provider.closes == 1
        assert not provider.close_cancelled.is_set()
        assert len(provider.calls) == len(case.before_send) == 1
    finally:
        provider.release()
        await _drain(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["claim", "begin", "result"])
async def test_real_deferred_postgres_commit_failures_never_create_send_permission(
    runtime_case, monkeypatch, phase
):
    case = runtime_case
    provider = _thread_provider(case, monkeypatch, "email")
    case.target_id = await _new_delivery(case)
    before = await case.db.delivery_row(case.target_id)
    if phase == "claim":
        await _reject_commit(case, phase)
        instance = worker.CommunicationWorker(
            session_factory=case.sessions,
            heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
        )
        with pytest.raises(
            SQLAlchemyError, match="synthetic notification deferred commit rejected"
        ):
            await asyncio.wait_for(instance.run_once(), timeout=WAIT_SECONDS)
        assert provider.calls == [] and case.before_send == []
        assert not provider.send_entered.is_set()
        assert await case.db.delivery_row(case.target_id) == before
        assert await case.db.registry_rows() == []
        assert await case.db.attempt_rows() == []
        return

    ownerships = await _claim(case)
    assert len(ownerships) == 1
    ownership = ownerships[0]
    await _reject_commit(case, phase)
    with pytest.raises(
        SQLAlchemyError, match="synthetic notification deferred commit rejected"
    ):
        await asyncio.wait_for(_process(case, ownership), timeout=WAIT_SECONDS)
    await _assert_uncertain(case)
    if phase == "begin":
        assert provider.calls == [] and case.before_send == []
        assert not provider.send_entered.is_set()
    else:
        assert len(provider.calls) == len(case.before_send) == 1
        assert provider.finished.is_set() and provider.closes == 1
    await _assert_no_resend(case, ownership)


@pytest.mark.asyncio
async def test_concurrent_and_replayed_capability_invoke_provider_only_once(
    runtime_case, monkeypatch
):
    case = runtime_case
    provider = _thread_provider(case, monkeypatch, "email")
    provider.send_release.clear()
    ownership = await _owned_delivery(case)
    tasks = [
        asyncio.create_task(_process(case, ownership)),
        asyncio.create_task(_process(case, ownership)),
    ]
    try:
        await _wait_thread(provider.send_entered)
        done, pending = await asyncio.wait(
            tasks, timeout=WAIT_SECONDS, return_when=asyncio.FIRST_COMPLETED
        )
        assert len(done) == len(pending) == 1
        loser = next(iter(done))
        with pytest.raises(activities.NotificationActivityOwnershipLost):
            await loser
        assert len(provider.calls) == 1
        closed = await case.db.close()
        await _closed_snapshot(case, closed)
        provider.release()
        result = await asyncio.wait_for(next(iter(pending)), timeout=WAIT_SECONDS)
        assert result.status == "delivered"
        await _assert_delivered(case)
        with pytest.raises(activities.NotificationActivityOwnershipLost):
            await _process(case, ownership)
        assert len(provider.calls) == 1
        assert (await case.db.snapshot(closed)).is_clear
    finally:
        provider.release()
        for task in tasks:
            await _drain(task)


@pytest.mark.asyncio
async def test_real_worker_drains_admitted_work_after_close_and_keeps_backlog_healthy(
    runtime_case, monkeypatch
):
    case = runtime_case
    provider = _thread_provider(case, monkeypatch, "email")
    provider.send_release.clear()
    case.target_id = await _new_delivery(case, priority=100)
    queued_id = await _new_delivery(case, priority=10)
    queued_before = await case.db.delivery_row(queued_id)
    instance = worker.CommunicationWorker(
        session_factory=case.sessions,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
    )
    task = asyncio.create_task(instance.run_forever())
    try:
        await _wait_thread(provider.send_entered)
        closed = await case.db.close()
        await _closed_snapshot(case, closed)
        old_health = json.loads(instance.health_path.read_text(encoding="utf-8"))
        async with asyncio.timeout(WAIT_SECONDS):
            while True:
                current = json.loads(instance.health_path.read_text(encoding="utf-8"))
                if current["checked_at_epoch"] > old_health["checked_at_epoch"]:
                    break
                await asyncio.sleep(0.01)
        assert current["status"] == "running"
        assert worker.healthcheck(instance.health_path) == 0
        assert not task.done() and not provider.finished.is_set()
        instance.stop_event.set()
        provider.release()
        await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert instance.processed == 1 and instance.errors == 0
        assert instance.last_delivery_id == case.target_id
        await _assert_delivered(case)
        assert await case.db.delivery_row(queued_id) == queued_before
        final = await case.db.snapshot(closed)
        assert final.is_clear and final.frozen_queued_ids == (queued_id,)
        assert json.loads(
            instance.health_path.read_text(encoding="utf-8")
        )["status"] == "stopped"

        # A subsequent real poll against the same valid closed authority is
        # healthy idle and cannot begin the still-pristine next queue row.
        instance.stop_event.clear()
        assert await instance.run_once() == 0
        assert worker.healthcheck(instance.health_path) == 0
        assert await case.db.delivery_row(queued_id) == queued_before
        assert len(provider.calls) == len(case.before_send) == 1
    finally:
        instance.stop_event.set()
        provider.release()
        await _drain(task)
