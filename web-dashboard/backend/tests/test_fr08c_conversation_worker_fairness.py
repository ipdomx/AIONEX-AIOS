from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import conversation_worker as worker


def _job(
    job_id: str,
    *,
    user: str,
    conversation: str,
    priority: int = 10,
    seconds: int = 0,
    organization: str = "org-1",
):
    return SimpleNamespace(
        id=job_id,
        organization_id=organization,
        status="queued",
        created_at=datetime(2026, 10, 3, tzinfo=UTC) + timedelta(seconds=seconds),
        payload={
            "requested_by_id": user,
            "conversation_id": conversation,
            "priority": priority,
        },
    )


def test_fair_batch_gives_each_user_a_first_slot_before_second_slot() -> None:
    rows = [
        _job("a-1", user="a", conversation="a-1", seconds=0),
        _job("a-2", user="a", conversation="a-2", seconds=1),
        _job("a-3", user="a", conversation="a-3", seconds=2),
        _job("b-1", user="b", conversation="b-1", seconds=3),
        _job("b-2", user="b", conversation="b-2", seconds=4),
    ]
    assert worker._fair_batch_ids(rows, limit=4) == ["a-1", "b-1", "a-2", "b-2"]


def test_fair_batch_allows_one_user_multiple_independent_conversations() -> None:
    rows = [
        _job("a-1", user="a", conversation="c-1", seconds=0),
        _job("a-2", user="a", conversation="c-2", seconds=1),
        _job("a-3", user="a", conversation="c-3", seconds=2),
    ]
    assert worker._fair_batch_ids(rows, limit=3) == ["a-1", "a-2", "a-3"]


def test_fair_batch_keeps_one_conversation_per_batch_and_respects_priority() -> None:
    rows = [
        _job("low", user="c", conversation="low", priority=1, seconds=0),
        _job("high-a-1", user="a", conversation="same", priority=20, seconds=1),
        _job("high-a-2", user="a", conversation="same", priority=20, seconds=2),
        _job("high-b", user="b", conversation="other", priority=20, seconds=3),
    ]
    assert worker._fair_batch_ids(rows, limit=3) == ["high-a-1", "high-b", "low"]


def test_active_job_is_not_scheduled_again() -> None:
    rows = [
        _job("active", user="a", conversation="c-1"),
        _job("next", user="b", conversation="c-2", seconds=1),
    ]
    assert worker._fair_batch_ids(rows, limit=2, active_job_ids={"active"}) == ["next"]


@pytest.mark.asyncio
async def test_worker_automatically_runs_independent_conversations_concurrently(monkeypatch) -> None:
    rows = [
        _job("a-1", user="a", conversation="a-1"),
        _job("b-1", user="b", conversation="b-1", seconds=1),
    ]
    release = asyncio.Event()
    both_started = asyncio.Event()
    started: set[str] = set()
    candidate_calls = 0

    async def candidates():
        nonlocal candidate_calls
        candidate_calls += 1
        return rows if candidate_calls == 1 else []

    async def run_turn(job_id: str) -> bool:
        started.add(job_id)
        if len(started) == 2:
            both_started.set()
        await release.wait()
        return True

    async def reconcile_stale_running():
        return 0

    monkeypatch.setattr(worker, "_queued_candidates", candidates)
    monkeypatch.setattr(worker, "run_turn", run_turn)
    monkeypatch.setattr(worker, "reconcile_stale_running", reconcile_stale_running)

    instance = worker.ConversationWorker(capacity=2)
    await instance.start()
    await asyncio.wait_for(both_started.wait(), timeout=1)
    assert started == {"a-1", "b-1"}
    release.set()
    await instance.stop()


@pytest.mark.asyncio
async def test_worker_cancels_unstarted_job_when_authority_changes(monkeypatch) -> None:
    rows = [_job("denied", user="a", conversation="a-1")]
    cancelled: list[tuple[str, str]] = []
    cancelled_event = asyncio.Event()
    candidate_calls = 0

    async def candidates():
        nonlocal candidate_calls
        candidate_calls += 1
        return rows if candidate_calls == 1 else []

    async def run_turn(job_id: str) -> bool:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="authority changed")

    async def cancel_unstarted(job_id: str, reason: str) -> None:
        cancelled.append((job_id, reason))
        cancelled_event.set()

    async def reconcile_stale_running():
        return 0

    monkeypatch.setattr(worker, "_queued_candidates", candidates)
    monkeypatch.setattr(worker, "run_turn", run_turn)
    monkeypatch.setattr(worker, "cancel_unstarted", cancel_unstarted)
    monkeypatch.setattr(worker, "reconcile_stale_running", reconcile_stale_running)

    instance = worker.ConversationWorker(capacity=1)
    await instance.start()
    await asyncio.wait_for(cancelled_event.wait(), timeout=1)
    assert cancelled == [("denied", "current_authority_unavailable")]
    await instance.stop()
