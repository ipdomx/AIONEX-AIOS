"""Notification worker task lifetime with controlled, entirely local dispatch.

These tests exercise the real process_delivery orchestration and worker loop with
explicitly replaced database preparation and settlement seams. PostgreSQL claim,
authority, and ownership fencing are covered by the companion database tests.
No SMTP, push, Telegram, WhatsApp, or other external provider is contacted.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services import communication_worker as worker
from app.services import communications
from app.services import host_maintenance_notifications as activities


WAIT_SECONDS = 10
HEARTBEAT_INTERVAL = 0.01


class SyntheticCleanupError(RuntimeError):
    """An injected provider cleanup failure with no network activity."""


class SyntheticCommitError(RuntimeError):
    """An injected failure acknowledging the final database transaction."""


class ThreadDispatch:
    """Keep actual thread execution and async-wrapper completion observable."""

    def __init__(self):
        self.loop_thread = threading.get_ident()
        self.entered = threading.Event()
        self.send_release = threading.Event()
        self.cleanup_entered = threading.Event()
        self.cleanup_release = threading.Event()
        self.finished = threading.Event()
        self.wrapper_finished = asyncio.Event()
        self.wrapper_cancelled = asyncio.Event()
        self.send_release.set()
        self.cleanup_release.set()
        self.calls = []
        self.failure = None
        self.cleanup_failure = None
        self.acknowledgement = "synthetic-provider-message"

    def _send_and_cleanup(self):
        assert threading.get_ident() != self.loop_thread
        self.entered.set()
        try:
            if not self.send_release.wait(WAIT_SECONDS):
                raise RuntimeError("synthetic dispatch barrier timed out")
            if self.failure is not None:
                raise self.failure
            return self.acknowledgement
        finally:
            try:
                self.cleanup_entered.set()
                if not self.cleanup_release.wait(WAIT_SECONDS):
                    raise RuntimeError("synthetic cleanup barrier timed out")
                if self.cleanup_failure is not None:
                    raise self.cleanup_failure
            finally:
                self.finished.set()

    async def __call__(self, data):
        self.calls.append(data)
        try:
            return await asyncio.to_thread(self._send_and_cleanup)
        except asyncio.CancelledError:
            self.wrapper_cancelled.set()
            raise
        finally:
            self.wrapper_finished.set()

    def release(self):
        self.send_release.set()
        self.cleanup_release.set()


async def wait_thread(event):
    async with asyncio.timeout(WAIT_SECONDS):
        while not event.is_set():
            await asyncio.sleep(0.005)


async def wait_async(event):
    await asyncio.wait_for(event.wait(), timeout=WAIT_SECONDS)


async def drain(task):
    if task is None:
        return
    if not task.done():
        task.cancel()
    await asyncio.wait_for(
        asyncio.gather(task, return_exceptions=True), timeout=WAIT_SECONDS
    )


class FakeSession:
    def __init__(self, case):
        self.case = case

    async def __aenter__(self):
        self.case.session_entries += 1
        return self

    async def __aexit__(self, *_exception):
        self.case.session_exits += 1
        return False

    def begin(self):
        return FakeTransaction(self.case)


class FakeTransaction:
    def __init__(self, case):
        self.case = case

    async def __aenter__(self):
        return self

    async def __aexit__(self, exception_type, *_exception):
        if exception_type is None:
            if self.case.begin_commit_failure is not None:
                raise self.case.begin_commit_failure
            self.case.begin_committed = True
        return False

@pytest.fixture
def dispatch_case(monkeypatch):
    ownership = activities.NotificationActivityOwnership(
        activity_id=str(uuid4()),
        delivery_id=str(uuid4()),
        attempt_number=1,
        worker_incarnation=str(uuid4()),
        admitted_generation=7,
        ownership_nonce="synthetic-private-nonce",
    )
    message = communications.NotificationMessageData(
        id=str(uuid4()),
        title="Synthetic private title",
        message="Synthetic private message",
        event_key="synthetic.notification",
        severity="info",
    )
    data = communications.NotificationDispatchData(
        channel="email",
        address="private-recipient@example.invalid",
        notification=message,
        telegram_scope="owner",
        endpoint_id=str(uuid4()),
    )
    case = SimpleNamespace(
        ownership=ownership,
        data=data,
        dispatcher=ThreadDispatch(),
        begins=[],
        begin_failure=None,
        begin_commit_failure=None,
        begin_committed=False,
        prepares=[],
        settlements=[],
        finishes=[],
        unresolved=[],
        heartbeats=[],
        ordered=[],
        unresolved_event=asyncio.Event(),
        heartbeat_event=asyncio.Event(),
        settled_event=asyncio.Event(),
        settlement_failure=None,
        heartbeat_failure=None,
        session_entries=0,
        session_exits=0,
    )
    case.sessions = lambda: FakeSession(case)

    async def begin(session, owner):
        assert isinstance(session, FakeSession) and owner is ownership
        if case.begin_failure is not None:
            raise case.begin_failure
        case.begins.append(owner)
        case.ordered.append("begin")

    async def prepare(owner, *, session_factory):
        assert owner is ownership and session_factory is case.sessions
        assert case.begin_committed
        case.prepares.append(owner)
        case.ordered.append("prepare")
        return data

    async def settle(owner, **kwargs):
        assert owner is ownership
        assert kwargs["session_factory"] is case.sessions
        assert case.dispatcher.finished.is_set()
        # The real PostgreSQL settlement fence rejects an unresolved activity.
        # The seam preserves that contract without claiming database coverage.
        if case.unresolved:
            raise activities.NotificationActivityOwnershipLost(
                "Synthetic activity is unresolved"
            )
        case.settlements.append(kwargs)
        case.ordered.append("settle")
        if case.settlement_failure is not None:
            raise case.settlement_failure
        case.settled_event.set()
        return communications.NotificationDispatchResult(
            delivery_id=ownership.delivery_id,
            status="delivered",
            attempt_count=ownership.attempt_number,
            provider_message_id=case.dispatcher.acknowledgement,
            dead_lettered_at=None,
        )

    async def heartbeat(owner, *, session_factory):
        assert owner is ownership and session_factory is case.sessions
        case.heartbeats.append(owner)
        case.heartbeat_event.set()
        if case.heartbeat_failure is not None:
            raise case.heartbeat_failure

    async def unresolved(owner, *, reason, session_factory):
        assert owner is ownership and session_factory is case.sessions
        case.unresolved.append(reason)
        case.ordered.append("unresolved")
        case.unresolved_event.set()

    async def finish(owner, *, session_factory):
        assert owner is ownership and session_factory is case.sessions
        assert case.dispatcher.finished.is_set()
        assert case.settled_event.is_set()
        case.finishes.append(owner)
        case.ordered.append("finish")

    async def forbid_real_dispatch(*_args, **_kwargs):
        raise AssertionError("Unit dispatch tests must not contact providers")

    monkeypatch.setattr(activities, "begin_notification_dispatch", begin)
    monkeypatch.setattr(communications, "_prepare_owned_notification_dispatch", prepare)
    monkeypatch.setattr(communications, "_settle_owned_notification_dispatch", settle)
    monkeypatch.setattr(communications, "_dispatch", forbid_real_dispatch)
    monkeypatch.setattr(activities, "heartbeat_notification_activity", heartbeat)
    monkeypatch.setattr(activities, "mark_notification_activity_unresolved", unresolved)
    monkeypatch.setattr(activities, "finish_notification_activity", finish)
    yield case
    case.dispatcher.release()


async def process(case, *, health_callback=None):
    return await communications.process_delivery(
        case.ownership,
        session_factory=case.sessions,
        dispatcher=case.dispatcher,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
        health_callback=health_callback,
    )


def test_dispatch_snapshot_is_immutable_and_omits_sensitive_repr(dispatch_case):
    case = dispatch_case
    assert case.data.notification is not None
    for value in (
        case.data.address,
        case.data.notification.title,
        case.data.notification.message,
    ):
        assert value not in repr(case.data)
    assert case.ownership.ownership_nonce not in repr(case.ownership)
    with pytest.raises(FrozenInstanceError):
        case.data.address = "replacement@example.invalid"
    with pytest.raises(FrozenInstanceError):
        case.data.notification.message = "replacement"
    with pytest.raises(FrozenInstanceError):
        case.ownership.worker_incarnation = str(uuid4())


@pytest.mark.asyncio
async def test_success_settles_only_after_provider_cleanup_then_finishes(dispatch_case):
    case = dispatch_case
    case.dispatcher.cleanup_release.clear()
    task = asyncio.create_task(process(case))
    try:
        await wait_thread(case.dispatcher.cleanup_entered)
        assert len(case.dispatcher.calls) == 1
        assert case.dispatcher.calls[0] is case.data
        assert not task.done() and not case.dispatcher.finished.is_set()
        assert case.settlements == [] and case.finishes == []
        case.dispatcher.cleanup_release.set()
        result = await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert result.delivery_id == case.ownership.delivery_id
        assert result.status == "delivered"
        assert result.provider_message_id == "synthetic-provider-message"
        assert result.attempt_count == 1
        with pytest.raises(FrozenInstanceError):
            result.provider_message_id = "replacement"
        assert case.ordered == ["begin", "prepare", "settle", "finish"]
        assert case.unresolved == []
        assert case.dispatcher.wrapper_finished.is_set()
        assert not case.dispatcher.wrapper_cancelled.is_set()
    finally:
        case.dispatcher.release()
        await drain(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["send", "cleanup"])
@pytest.mark.parametrize(
    "repeat_cancel", [False, True], ids=["cancel", "repeated-cancel"]
)
async def test_cancellation_retains_real_thread_and_marks_before_waiting(
    dispatch_case, phase, repeat_cancel
):
    case = dispatch_case
    if phase == "send":
        case.dispatcher.send_release.clear()
        entered = case.dispatcher.entered
    else:
        case.dispatcher.cleanup_release.clear()
        entered = case.dispatcher.cleanup_entered
    task = asyncio.create_task(process(case))
    try:
        await wait_thread(entered)
        task.cancel()
        await wait_async(case.unresolved_event)
        assert not task.done()
        assert not case.dispatcher.finished.is_set()
        assert not case.dispatcher.wrapper_cancelled.is_set()
        assert case.finishes == [] and case.settlements == []
        if repeat_cancel:
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert not case.dispatcher.wrapper_cancelled.is_set()
        case.dispatcher.release()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert case.dispatcher.finished.is_set()
        assert case.dispatcher.wrapper_finished.is_set()
        assert not case.dispatcher.wrapper_cancelled.is_set()
        assert len(case.dispatcher.calls) == 1
        assert case.unresolved and case.finishes == [] and case.settlements == []
    finally:
        case.dispatcher.release()
        await drain(task)


@pytest.mark.asyncio
async def test_heartbeat_failure_retains_marker_and_joins_blocked_dispatch(
    dispatch_case,
):
    case = dispatch_case
    case.dispatcher.send_release.clear()
    case.heartbeat_failure = activities.NotificationActivityRegistryUnavailable(
        "synthetic-heartbeat-unavailable"
    )
    task = asyncio.create_task(process(case))
    try:
        await wait_thread(case.dispatcher.entered)
        await wait_async(case.unresolved_event)
        assert case.heartbeats
        assert not task.done() and not case.dispatcher.finished.is_set()
        assert not case.dispatcher.wrapper_cancelled.is_set()
        assert case.finishes == [] and case.settlements == []
        case.dispatcher.release()
        with pytest.raises(activities.NotificationActivityRegistryUnavailable):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert case.dispatcher.finished.is_set()
        assert case.dispatcher.wrapper_finished.is_set()
        assert case.finishes == [] and case.settlements == []
        assert len(case.dispatcher.calls) == 1
    finally:
        case.dispatcher.release()
        await drain(task)


@pytest.mark.asyncio
async def test_success_waits_for_heartbeat_crossing_business_settlement(
    dispatch_case, monkeypatch
):
    case = dispatch_case
    case.dispatcher.send_release.clear()
    heartbeat_entered = asyncio.Event()
    heartbeat_release = asyncio.Event()
    heartbeat_finished = asyncio.Event()

    async def heartbeat(owner, *, session_factory):
        assert owner is case.ownership and session_factory is case.sessions
        heartbeat_entered.set()
        try:
            await heartbeat_release.wait()
        finally:
            heartbeat_finished.set()

    monkeypatch.setattr(activities, "heartbeat_notification_activity", heartbeat)
    task = asyncio.create_task(process(case))
    try:
        await wait_thread(case.dispatcher.entered)
        await wait_async(heartbeat_entered)
        case.dispatcher.release()
        await wait_async(case.settled_event)
        assert case.finishes == []
        heartbeat_release.set()
        result = await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert heartbeat_finished.is_set()
        assert result.status == "delivered"
        assert case.unresolved == []
        assert case.finishes == [case.ownership]
    finally:
        heartbeat_release.set()
        case.dispatcher.release()
        await drain(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_location", ["dispatch", "cleanup"])
async def test_ambiguous_execution_or_cleanup_failure_never_finishes_or_resends(
    dispatch_case, failure_location
):
    case = dispatch_case
    failure = SyntheticCleanupError("synthetic-private-provider-detail")
    if failure_location == "dispatch":
        case.dispatcher.failure = failure
    else:
        case.dispatcher.cleanup_failure = failure
    with pytest.raises(communications.NotificationDispatchUncertain):
        await asyncio.wait_for(process(case), timeout=WAIT_SECONDS)
    assert case.dispatcher.finished.is_set()
    assert len(case.dispatcher.calls) == 1
    assert case.unresolved and case.finishes == [] and case.settlements == []
    assert all(
        "synthetic-private-provider-detail" not in reason for reason in case.unresolved
    )


@pytest.mark.asyncio
async def test_unacknowledged_result_commit_keeps_owner_without_resend(dispatch_case):
    case = dispatch_case
    case.settlement_failure = SyntheticCommitError("synthetic-private-commit-detail")
    with pytest.raises(SyntheticCommitError):
        await asyncio.wait_for(process(case), timeout=WAIT_SECONDS)
    assert case.dispatcher.finished.is_set()
    assert len(case.dispatcher.calls) == 1 and len(case.settlements) == 1
    assert case.unresolved and case.finishes == []
    assert all(
        "synthetic-private-commit-detail" not in reason for reason in case.unresolved
    )


@pytest.mark.asyncio
async def test_long_blocked_dispatch_refreshes_health_without_early_settlement(
    dispatch_case,
):
    case = dispatch_case
    case.dispatcher.send_release.clear()
    health_updates = []
    refreshed_twice = asyncio.Event()

    def health():
        health_updates.append(len(health_updates))
        if len(health_updates) >= 2:
            refreshed_twice.set()

    task = asyncio.create_task(process(case, health_callback=health))
    try:
        await wait_thread(case.dispatcher.entered)
        await wait_async(refreshed_twice)
        assert not task.done() and not case.dispatcher.finished.is_set()
        assert case.settlements == [] and case.finishes == []
        assert case.heartbeats
        case.dispatcher.release()
        result = await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert result.status == "delivered"
        assert case.unresolved == []
    finally:
        case.dispatcher.release()
        await drain(task)

@pytest.mark.asyncio
async def test_worker_claims_at_most_one_and_passes_immutable_capability(
    dispatch_case, monkeypatch, tmp_path
):
    case = dispatch_case
    claims = []
    dispatched = []
    health = []

    async def claim(session, *, worker_incarnation, limit):
        assert isinstance(session, FakeSession)
        claims.append((worker_incarnation, limit))
        return [case.ownership]

    async def deliver(ownership, **kwargs):
        assert ownership is case.ownership
        assert kwargs["session_factory"] is case.sessions
        assert kwargs["dispatcher"] is case.dispatcher
        assert callable(kwargs["health_callback"])
        dispatched.append(ownership)
        return communications.NotificationDispatchResult(
            delivery_id=ownership.delivery_id,
            status="delivered",
            attempt_count=1,
            provider_message_id="synthetic-provider-message",
            dead_lettered_at=None,
        )

    monkeypatch.setattr(worker, "claim_due_deliveries", claim)
    monkeypatch.setattr(worker, "process_delivery", deliver)
    instance = worker.CommunicationWorker(
        session_factory=case.sessions,
        dispatcher=case.dispatcher,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
    )
    instance.health_path = tmp_path / "notification-health.json"
    monkeypatch.setattr(instance, "write_health", health.append)
    assert await instance.run_once() == 1
    assert len(claims) == 1 and claims[0][1] == 1
    assert claims[0][0] == instance.worker_incarnation
    assert dispatched == [case.ownership]
    assert instance.processed == 1
    assert instance.last_delivery_id == case.ownership.delivery_id
    assert instance.errors == 0
    assert health and health[-1] == "running"
    assert case.session_entries == case.session_exits == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "closed_exception", [False, True], ids=["no-eligible-row", "closed"]
)
async def test_closed_poll_is_healthy_idle_and_never_enters_dispatch(
    dispatch_case, monkeypatch, tmp_path, closed_exception
):
    case = dispatch_case
    claims = []
    health = []

    async def closed_claim(session, *, worker_incarnation, limit):
        assert isinstance(session, FakeSession)
        claims.append((worker_incarnation, limit))
        if closed_exception:
            raise worker.HostMaintenanceClosed(SimpleNamespace(state="closed"))
        return []

    async def forbidden_delivery(*_args, **_kwargs):
        raise AssertionError("Closed admission must not start provider execution")

    monkeypatch.setattr(worker, "claim_due_deliveries", closed_claim)
    monkeypatch.setattr(worker, "process_delivery", forbidden_delivery)
    instance = worker.CommunicationWorker(
        session_factory=case.sessions,
        dispatcher=case.dispatcher,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
    )
    instance.health_path = tmp_path / "closed-health.json"
    monkeypatch.setattr(instance, "write_health", health.append)
    assert await instance.run_once() == 0
    assert len(claims) == 1 and claims[0][1] == 1
    assert instance.processed == 0 and instance.errors == 0
    assert health and health[-1] == "running"
    assert case.dispatcher.calls == []


@pytest.mark.asyncio
async def test_unavailable_authority_is_degraded_without_dispatch(
    dispatch_case, monkeypatch, tmp_path
):
    case = dispatch_case
    health = []

    async def unavailable_claim(_session, *, worker_incarnation, limit):
        assert worker_incarnation and limit == 1
        raise activities.NotificationActivityRegistryUnavailable(
            "synthetic-authority-unavailable"
        )

    async def forbidden_delivery(*_args, **_kwargs):
        raise AssertionError("Unavailable authority must not start dispatch")

    monkeypatch.setattr(worker, "claim_due_deliveries", unavailable_claim)
    monkeypatch.setattr(worker, "process_delivery", forbidden_delivery)
    instance = worker.CommunicationWorker(
        session_factory=case.sessions,
        dispatcher=case.dispatcher,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
    )
    instance.health_path = tmp_path / "unavailable-health.json"

    async def preflight():
        return None

    def record_health(status):
        health.append(status)
        if status == "degraded":
            instance.stop_event.set()

    monkeypatch.setattr(instance, "preflight", preflight)
    monkeypatch.setattr(instance, "write_health", record_health)
    await asyncio.wait_for(instance.run_forever(), timeout=WAIT_SECONDS)
    assert "degraded" in health
    assert health[-1] == "stopped"
    assert instance.processed == 0 and instance.errors == 1
    assert case.dispatcher.calls == []


@pytest.mark.asyncio
async def test_stop_request_drains_current_operation_without_next_claim(
    dispatch_case, monkeypatch, tmp_path
):
    case = dispatch_case
    case.dispatcher.send_release.clear()
    claims = []
    health = []

    async def claim(_session, *, worker_incarnation, limit):
        claims.append((worker_incarnation, limit))
        return [case.ownership]

    async def preflight():
        return None

    monkeypatch.setattr(worker, "claim_due_deliveries", claim)
    instance = worker.CommunicationWorker(
        session_factory=case.sessions,
        dispatcher=case.dispatcher,
        heartbeat_interval_seconds=HEARTBEAT_INTERVAL,
    )
    instance.health_path = tmp_path / "stop-health.json"
    monkeypatch.setattr(instance, "preflight", preflight)
    monkeypatch.setattr(instance, "write_health", health.append)
    task = asyncio.create_task(instance.run_forever())
    try:
        await wait_thread(case.dispatcher.entered)
        instance.stop_event.set()
        await wait_async(case.heartbeat_event)
        assert not task.done() and not case.dispatcher.finished.is_set()
        assert len(claims) == 1
        case.dispatcher.release()
        await asyncio.wait_for(task, timeout=WAIT_SECONDS)
        assert len(claims) == 1 and claims[0][1] == 1
        assert case.finishes == [case.ownership] and case.unresolved == []
        assert not case.dispatcher.wrapper_cancelled.is_set()
        assert instance.processed == 1 and health[-1] == "stopped"
    finally:
        case.dispatcher.release()
        await drain(task)

@pytest.mark.asyncio
async def test_begin_commit_uncertainty_starts_no_provider_operation(dispatch_case):
    case = dispatch_case
    case.begin_commit_failure = SyntheticCommitError(
        "synthetic begin commit uncertainty"
    )
    with pytest.raises(SyntheticCommitError):
        await asyncio.wait_for(process(case), timeout=WAIT_SECONDS)
    assert case.begins == [case.ownership]
    assert not case.begin_committed
    assert case.prepares == [] and case.dispatcher.calls == []
    assert not case.dispatcher.entered.is_set()
    assert case.unresolved and case.finishes == [] and case.settlements == []


@pytest.mark.asyncio
async def test_rejected_capability_starts_nothing_and_cannot_mark_another_owner(
    dispatch_case,
):
    case = dispatch_case
    case.begin_failure = activities.NotificationActivityOwnershipLost(
        "synthetic capability already consumed"
    )
    with pytest.raises(activities.NotificationActivityOwnershipLost):
        await asyncio.wait_for(process(case), timeout=WAIT_SECONDS)
    assert case.begins == [] and not case.begin_committed
    assert case.prepares == [] and case.dispatcher.calls == []
    assert case.unresolved == [] and case.finishes == [] and case.settlements == []


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledgement", ["", "   ", None, "x" * 256])
async def test_invalid_provider_acknowledgement_retains_uncertainty_without_resend(
    dispatch_case, acknowledgement
):
    case = dispatch_case
    case.dispatcher.acknowledgement = acknowledgement
    with pytest.raises(communications.NotificationDispatchUncertain):
        await asyncio.wait_for(process(case), timeout=WAIT_SECONDS)
    assert case.dispatcher.finished.is_set()
    assert len(case.dispatcher.calls) == 1
    assert case.unresolved and case.finishes == [] and case.settlements == []
