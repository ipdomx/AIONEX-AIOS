"""Observer maintenance acceptance on disposable PostgreSQL only.

Production worker methods, transactions, admission and SQL locks are real.
Ordinary probes/provider calls/publication are explicit test doubles. Safety
callbacks in the narrow ordering tests write real durable sentinel audits;
existing growth suites separately exercise actual disarm/review semantics.
"""
from __future__ import annotations

import importlib
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.models import AuditEvent, OwnerControlRecord
from app.services import host_maintenance_admission as maintenance
from app.services import operations_observer as observer_module
from tests.test_fr06d10a_media_claim_fence import _open
from tests.test_fr06d10a_media_claim_fence import case as case


def _fence():
    try:
        return importlib.import_module("app.services.host_maintenance_observer")
    except ModuleNotFoundError as exc:
        if exc.name != "app.services.host_maintenance_observer":
            raise
        return None


async def _authority(case, state):
    if state == "closed":
        return
    async with case.sessions() as session, session.begin():
        row = await session.get(OwnerControlRecord, case.authority_id)
        if state == "missing":
            await session.delete(row)
        elif state == "schema7":
            row.status, row.enabled = "open", True
            row.payload = {**row.payload, "schema_version": 7,
                           "scope": maintenance.STUDIO_REQUEST_COVERAGE_SCOPE}
        elif state == "malformed":
            row.payload = {"unexpected": True}
        else:
            raise AssertionError(state)
    case.sql.clear()


def _observer(case, monkeypatch, tmp_path):
    monkeypatch.setattr(observer_module, "SessionLocal", case.sessions)
    helper = _fence()
    if helper is not None:
        monkeypatch.setattr(helper, "SessionLocal", case.sessions)
    monkeypatch.setattr(settings, "PROJECT_AI_MODEL_REFRESH_ENABLED", True)
    worker = observer_module.OperationsObserver()
    worker.health_path = tmp_path / "observer-health.json"
    effects = []

    async def safety(session):
        session.add(AuditEvent(action="synthetic.observer.auto_disarm", resource_type="test",
                               resource_id=uuid4().hex, details={"real_provider_call": False}))
        return {"auto_disarmed": 1}

    async def review(session):
        session.add(AuditEvent(action="synthetic.observer.manual_review", resource_type="test",
                               resource_id=uuid4().hex, details={"remote_settled": False}))
        return {"executions_marked_manual_review": 1, "pilots_auto_disarmed": 0}

    async def observation(session):
        effects.append("observation")
        session.add(AuditEvent(action="synthetic.observer.observation", resource_type="test",
                               resource_id=uuid4().hex, details={}))
        await session.flush()
        return []

    async def refresh(session):
        effects.append("model-refresh")
        session.add(AuditEvent(action="synthetic.observer.refresh", resource_type="test",
                               resource_id=uuid4().hex, details={}))
        return {"notifications": ["synthetic-model-notification"]}

    async def lifecycle(session):
        effects.append("lifecycle")
        return ["synthetic-lifecycle-notification"]

    async def runtime(session):
        effects.append("runtime")
        return []

    async def credit(session):
        effects.append("credit")
        return []

    async def publish(notifications):
        effects.append(("publish", tuple(notifications)))

    for name, callback in (("reconcile_runtime_pilots", safety),
                           ("reconcile_stale_live_executions", review),
                           ("record_observation_cycle", observation),
                           ("refresh_launch_model_evidence", refresh),
                           ("run_account_lifecycle_alerts", lifecycle),
                           ("run_runtime_owner_alerts", runtime),
                           ("run_provider_credit_alerts", credit)):
        monkeypatch.setattr(observer_module, name, callback)
    monkeypatch.setattr(observer_module.communications, "publish_many", publish)
    return worker, effects


async def _audits(case):
    async with case.sessions() as session:
        return list((await session.scalars(select(AuditEvent.action)
            .where(AuditEvent.action.like("synthetic.observer.%")).order_by(AuditEvent.action))).all())


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["preflight", "run_once"])
@pytest.mark.parametrize("state", ["closed", "missing", "schema7", "malformed"])
async def test_denied_observation_preserves_safety_without_probes_or_notifications(case, monkeypatch, tmp_path, method, state):
    await _authority(case, state)
    worker, effects = _observer(case, monkeypatch, tmp_path)
    await getattr(worker, method)()
    assert effects == []
    assert worker.cycles == 0
    assert worker.last_project_ai_model_refresh_monotonic == 0
    assert worker.last_lifecycle_alert_monotonic == 0
    assert worker.last_provider_credit_alert_monotonic == 0
    assert await _audits(case) == ([] if method == "preflight" else [
        "synthetic.observer.auto_disarm", "synthetic.observer.manual_review"])


@pytest.mark.asyncio
async def test_open_preflight_keeps_rollback_without_durable_observation(case, monkeypatch, tmp_path):
    await _open(case)
    worker, effects = _observer(case, monkeypatch, tmp_path)
    await worker.preflight()
    assert effects == ["observation"]
    assert await _audits(case) == []


@pytest.mark.asyncio
async def test_open_cycle_preserves_model_alert_schedule_and_durable_safety(case, monkeypatch, tmp_path):
    await _open(case)
    worker, effects = _observer(case, monkeypatch, tmp_path)
    await worker.run_once()
    assert effects == ["model-refresh", ("publish", ("synthetic-model-notification",)),
                       "observation", "lifecycle", "runtime", "credit",
                       ("publish", ("synthetic-lifecycle-notification",))]
    assert worker.cycles == 1 and worker.last_project_ai_model_refresh_monotonic > 0
    assert len(await _audits(case)) == 4


@pytest.mark.asyncio
async def test_safety_commit_survives_later_ordinary_failure(case, monkeypatch, tmp_path):
    await _open(case)
    worker, _ = _observer(case, monkeypatch, tmp_path)

    async def fail(session):
        raise RuntimeError("Synthetic ordinary provider failure")

    monkeypatch.setattr(observer_module, "refresh_launch_model_evidence", fail)
    with pytest.raises(RuntimeError, match="Synthetic ordinary provider failure"):
        await worker.run_once()
    assert await _audits(case) == ["synthetic.observer.auto_disarm", "synthetic.observer.manual_review"]
    assert worker.cycles == 0 and worker.last_project_ai_model_refresh_monotonic == 0


async def _observed_fence(case, monkeypatch):
    from sqlalchemy import text
    module = _fence()
    assert module is not None
    monkeypatch.setattr(module, "SessionLocal", case.sessions)
    original = module._open
    holder = {}

    async def open_observed(session):
        result = await original(session)
        holder["pid"] = await session.scalar(text("SELECT pg_backend_pid()"))
        return result

    monkeypatch.setattr(module, "_open", open_observed)
    return module, holder


async def _close(case):
    return await maintenance.close_admission(operation_id=case.operation,
        expected_generation=26, reason="Synthetic observer closure", session_factory=case.sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["model", "alerts"])
@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
async def test_observer_lock_spans_business_commit_and_postcommit_publication(case, monkeypatch, tmp_path, phase, outcome):
    import asyncio
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock

    await _open(case)
    worker, _ = _observer(case, monkeypatch, tmp_path)
    _, holder = await _observed_fence(case, monkeypatch)
    entered, release = asyncio.Event(), asyncio.Event()
    publications = []

    async def publish(notifications):
        publications.append(tuple(notifications))
        if bool("synthetic-model-notification" in notifications) == (phase == "model"):
            # The caller committed its work before this publisher was invoked.
            assert "synthetic.observer.refresh" in await _audits(case)
            if phase == "alerts":
                assert "synthetic.observer.observation" in await _audits(case)
            entered.set()
            await release.wait()
            if outcome == "failure":
                raise RuntimeError("Synthetic publication failure after commit")

    monkeypatch.setattr(observer_module.communications, "publish_many", publish)
    request = asyncio.create_task(worker.run_once())
    closing = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        closing = asyncio.create_task(_close(case))
        await _wait_for_lock(case, holder["pid"])
        assert not closing.done()
        if outcome == "cancel":
            request.cancel()
            await asyncio.sleep(.02)
            request.cancel()
            await asyncio.sleep(.02)
            assert not request.done() and not closing.done()
        release.set()
        if outcome == "failure":
            with pytest.raises(RuntimeError, match="Synthetic publication failure"):
                await asyncio.wait_for(request, 3)
        elif outcome == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(request, 3)
        else:
            await asyncio.wait_for(request, 3)
        assert (await asyncio.wait_for(closing, 3)).generation == 27
        assert len(publications) == len(set(publications))
        assert "synthetic.observer.auto_disarm" in await _audits(case)
    finally:
        release.set()
        await asyncio.gather(request, *([closing] if closing else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["preflight", "run_once"])
async def test_closer_first_refuses_ordinary_work_after_actual_postgresql_wait(case, monkeypatch, tmp_path, method):
    import asyncio
    from sqlalchemy import text
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock

    await _open(case)
    worker, effects = _observer(case, monkeypatch, tmp_path)
    async with case.sessions() as closer:
        _, snapshot = await maintenance._locked_snapshot(closer, exclusive=True)
        assert snapshot.is_open
        pid = await closer.scalar(text("SELECT pg_backend_pid()"))
        row = await closer.get(OwnerControlRecord, case.authority_id)
        row.status, row.enabled = "closed", False
        row.version = 27
        row.payload = {**row.payload, "generation": 27}
        await closer.flush()
        request = asyncio.create_task(getattr(worker, method)())
        try:
            await _wait_for_lock(case, pid)
            assert not request.done() and effects == []
            await closer.commit()
            await asyncio.wait_for(request, 3)
            assert effects == [] and worker.cycles == 0
        finally:
            await closer.rollback()
            if not request.done():
                request.cancel()
            await asyncio.gather(request, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_cancellation_waits_for_real_owned_thread_before_releasing_admission(case, monkeypatch, tmp_path, fails):
    import asyncio
    import threading
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock

    await _open(case)
    worker, _ = _observer(case, monkeypatch, tmp_path)
    _, holder = await _observed_fence(case, monkeypatch)
    entered = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    path = tmp_path / "synthetic-observer-thread.txt"
    calls = []

    def work():
        calls.append(1)
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        try:
            path.write_text("owned effect complete")
            if fails:
                raise RuntimeError("Synthetic thread failure")
        finally:
            finished.set()

    async def refresh(session):
        await asyncio.to_thread(work)
        return {"notifications": []}

    monkeypatch.setattr(observer_module, "refresh_launch_model_evidence", refresh)
    request = asyncio.create_task(worker.run_once())
    closing = None
    try:
        await asyncio.wait_for(entered.wait(), 3)
        closing = asyncio.create_task(_close(case))
        await _wait_for_lock(case, holder["pid"])
        for _ in range(3):
            request.cancel()
            await asyncio.sleep(.02)
        assert not finished.is_set() and not request.done() and not closing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(request, 3)
        assert (await asyncio.wait_for(closing, 3)).generation == 27
        assert finished.is_set() and calls == [1] and path.read_text() == "owned effect complete"
        assert not [t for t in asyncio.all_tasks() if not t.done() and t.get_name() == "aionex-maintenance-bound-observer"]
    finally:
        release.set()
        await asyncio.gather(request, *([closing] if closing else []), return_exceptions=True)


@pytest.mark.asyncio
async def test_safety_failure_rolls_back_safety_and_never_starts_ordinary_work(case, monkeypatch, tmp_path):
    await _open(case)
    worker, effects = _observer(case, monkeypatch, tmp_path)

    async def fail(session):
        raise RuntimeError("Synthetic safety reconciliation failure")

    monkeypatch.setattr(observer_module, "reconcile_stale_live_executions", fail)
    with pytest.raises(RuntimeError, match="Synthetic safety reconciliation failure"):
        await worker.run_once()
    assert effects == [] and await _audits(case) == []


@pytest.mark.asyncio
async def test_stop_after_safety_commits_skips_new_ordinary_cycle(case, monkeypatch, tmp_path):
    await _open(case)
    worker, effects = _observer(case, monkeypatch, tmp_path)
    original = observer_module.reconcile_stale_live_executions

    async def stop(session):
        result = await original(session)
        worker.stop_event.set()
        return result

    monkeypatch.setattr(observer_module, "reconcile_stale_live_executions", stop)
    await worker.run_once()
    assert effects == [] and worker.cycles == 0
    assert await _audits(case) == ["synthetic.observer.auto_disarm", "synthetic.observer.manual_review"]


@pytest.mark.asyncio
async def test_cached_open_authority_cannot_admit_observation_after_close(case, monkeypatch):
    await _open(case)
    helper = _fence()
    assert helper is not None
    async with case.sessions() as session:
        row = await session.get(OwnerControlRecord, case.authority_id)
        await session.commit()
        assert row.status == "open"
        await _close(case)
        assert row.status == "open"  # Stale ORM fixture; reader must select raw values.
        assert await helper._open(session) is False
        await session.rollback()


@pytest.mark.asyncio
async def test_cancel_during_admission_wait_never_constructs_action(case, monkeypatch):
    import asyncio
    from sqlalchemy import text
    from tests.test_fr06d10a_media_claim_fence import _wait_for_lock

    await _open(case)
    helper = _fence()
    monkeypatch.setattr(helper, "SessionLocal", case.sessions)
    effects = []

    def action():
        effects.append(1)
        raise AssertionError("Action factory must not run before admission")

    async with case.sessions() as closer:
        await maintenance._locked_snapshot(closer, exclusive=True)
        pid = await closer.scalar(text("SELECT pg_backend_pid()"))
        task = asyncio.create_task(helper.run_observer_observation(action))
        try:
            await _wait_for_lock(case, pid)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 3)
            assert effects == []
        finally:
            await closer.rollback()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError, RuntimeError])
async def test_authority_unavailability_denies_but_programming_errors_propagate(case, monkeypatch, error):
    helper = _fence()
    monkeypatch.setattr(helper, "SessionLocal", case.sessions)
    called = []

    async def fail(session):
        raise error("synthetic")

    async def action():
        called.append(True)

    monkeypatch.setattr(helper, "read_admission_snapshot", fail)
    if error is OSError:
        assert await helper.run_observer_observation(action) is False
    else:
        with pytest.raises(RuntimeError, match="synthetic"):
            await helper.run_observer_observation(action)
    assert not called


def test_observer_lock_engine_is_independent_of_business_connections():
    from app.db.base import SessionLocal
    helper = _fence()
    assert helper.SessionLocal.kw["bind"] is not SessionLocal.kw["bind"]


@pytest.mark.asyncio
@pytest.mark.parametrize("closed", [True, False])
async def test_real_pilot_auto_disarm_survives_closed_or_failing_observer(case, monkeypatch, tmp_path, closed):
    from datetime import UTC, datetime, timedelta
    from app.db.base import Base
    from app.db.models import GrowthControlledPilot
    from app.services.growth_controlled_pilots import reconcile_runtime_pilots
    from app.services.growth_paid_live_execution import reconcile_stale_live_executions

    # Add the real growth tables only to this exclusively owned disposable schema.
    async with case.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    if not closed:
        await _open(case)
    pid = str(uuid4())
    async with case.sessions() as session, session.begin():
        session.add(GrowthControlledPilot(id=pid, organization_id=case.oid,
            created_by_id=case.uid, provider="meta", provider_scope="ad_account",
            scope_ref="synthetic://" + uuid4().hex, mode="live_spend", capability="ads.manage",
            status="armed", launch_authorized=True, live_provider_mutation_allowed=True,
            real_spend_allowed=True, expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    worker, effects = _observer(case, monkeypatch, tmp_path)
    monkeypatch.setattr(observer_module, "reconcile_runtime_pilots", reconcile_runtime_pilots)
    monkeypatch.setattr(observer_module, "reconcile_stale_live_executions", reconcile_stale_live_executions)

    async def fail(session):
        raise RuntimeError("Synthetic unrelated ordinary failure")

    monkeypatch.setattr(observer_module, "refresh_launch_model_evidence", fail)
    if closed:
        await worker.run_once()
    else:
        with pytest.raises(RuntimeError, match="Synthetic unrelated ordinary failure"):
            await worker.run_once()
    async with case.sessions() as session:
        pilot = await session.get(GrowthControlledPilot, pid)
        assert pilot.status == "auto_disarmed"
        assert pilot.real_spend_allowed is False and pilot.live_provider_mutation_allowed is False
        assert pilot.launch_authorized is False and pilot.disarmed_at is not None
        audits = list((await session.scalars(select(AuditEvent).where(
            AuditEvent.action == "growth.pilot.runtime_auto_disarmed", AuditEvent.resource_id == pid))).all())
        assert len(audits) == 1 and audits[0].details["automatic_execution_allowed"] is False
    assert effects == []
