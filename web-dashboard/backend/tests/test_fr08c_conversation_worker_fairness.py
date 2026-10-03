"""FR08C automatic queue fairness and bounded concurrency acceptance."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import conversation_worker as worker


def row(job_id: str, user: str, conversation: str, *, priority: int = 0, org: str = "org"):
    return SimpleNamespace(
        id=job_id,
        organization_id=org,
        payload={
            "requested_by_id": user,
            "conversation_id": conversation,
            "priority": priority,
        },
    )


def test_fair_job_ids_round_robins_users_within_priority():
    rows = [
        row("a1", "alice", "a-1", priority=4),
        row("a2", "alice", "a-2", priority=4),
        row("a3", "alice", "a-3", priority=4),
        row("b1", "bob", "b-1", priority=4),
        row("b2", "bob", "b-2", priority=4),
        row("c1", "carol", "c-1", priority=4),
    ]
    assert worker.fair_job_ids(rows, limit=6) == ["a1", "b1", "c1", "a2", "b2", "a3"]


def test_fair_job_ids_preserves_priority_and_one_conversation_per_wave():
    rows = [
        row("high-a1", "alice", "shared", priority=9),
        row("high-a2", "alice", "shared", priority=9),
        row("high-b", "bob", "b", priority=9),
        row("low-c", "carol", "c", priority=1),
    ]
    assert worker.fair_job_ids(rows, limit=4) == ["high-a1", "high-b", "low-c"]


def test_fair_job_ids_is_bounded():
    rows = [row(f"j{i}", f"u{i}", f"c{i}", priority=2) for i in range(20)]
    assert len(worker.fair_job_ids(rows)) == worker.DISPATCH_BATCH_SIZE


@pytest.mark.asyncio
async def test_worker_batch_runs_selected_jobs_concurrently(monkeypatch):
    active = 0
    peak = 0
    entered = 0
    ready = asyncio.Event()
    release = asyncio.Event()

    async def fake_run_turn(job_id: str) -> bool:
        nonlocal active, peak, entered
        active += 1
        peak = max(peak, active)
        entered += 1
        if entered == 4:
            ready.set()
        try:
            await release.wait()
            return True
        finally:
            active -= 1

    monkeypatch.setattr(worker, "run_turn", fake_run_turn)
    instance = worker.ConversationWorker()
    task = asyncio.create_task(instance._run_batch(["a", "b", "c", "d"]))
    try:
        await asyncio.wait_for(ready.wait(), 2)
        assert peak == 4
        release.set()
        assert await asyncio.wait_for(task, 2) is True
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_worker_batch_cancels_unstarted_authority_failures(monkeypatch):
    cancelled = []

    async def denied(job_id: str) -> bool:
        raise HTTPException(status_code=404, detail="synthetic")

    async def cancel(job_id: str, reason: str) -> None:
        cancelled.append((job_id, reason))

    monkeypatch.setattr(worker, "run_turn", denied)
    monkeypatch.setattr(worker, "cancel_unstarted", cancel)
    instance = worker.ConversationWorker()
    assert await instance._run_batch(["a", "b"]) is True
    assert cancelled == [
        ("a", "current_authority_unavailable"),
        ("b", "current_authority_unavailable"),
    ]
