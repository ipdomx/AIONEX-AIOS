from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services import conversation_worker as worker


def _job(job_id: str, *, user: str, conversation: str, seconds: int, status: str = "queued"):
    return SimpleNamespace(
        id=job_id,
        organization_id="org-1",
        status=status,
        created_at=datetime(2026, 10, 3, tzinfo=UTC) + timedelta(seconds=seconds),
        payload={
            "requested_by_id": user,
            "conversation_id": conversation,
            "priority": 10,
        },
    )


def test_queue_wait_measurement_is_exact_and_never_fabricates_negative_or_missing() -> None:
    row = _job("a", user="a", conversation="c-a", seconds=10)
    started = datetime(2026, 10, 3, tzinfo=UTC) + timedelta(seconds=12, milliseconds=345)
    assert worker._queue_wait_ms(row, started) == 2345

    missing = _job("missing", user="a", conversation="c-missing", seconds=0)
    missing.created_at = None
    assert worker._queue_wait_ms(missing, started) is None

    future = _job("future", user="a", conversation="c-future", seconds=20)
    assert worker._queue_wait_ms(future, started) is None


def test_restart_candidate_scan_never_replays_running_work_and_keeps_multi_user_fairness() -> None:
    rows = [
        _job("running-a", user="a", conversation="a-running", seconds=0, status="running"),
        _job("queued-a", user="a", conversation="a-next", seconds=1),
        _job("queued-b", user="b", conversation="b-1", seconds=2),
        _job("queued-c", user="c", conversation="c-1", seconds=3),
    ]
    assert worker._fair_batch_ids(rows, limit=3) == ["queued-a", "queued-b", "queued-c"]


def test_dispatch_source_persists_wait_evidence_before_provider_io() -> None:
    source = open(worker.__file__, encoding="utf-8").read()
    assert '"dispatch_queue_wait_ms": queue_wait_ms' in source
    assert '"queue_wait_ms": queue_wait_ms' in source
    assert (
        "await session.commit()"
        in source
        and "result = await ai._execute_provider" in source
        and source.index("await session.commit()")
        < source.index("result = await ai._execute_provider")
    )
