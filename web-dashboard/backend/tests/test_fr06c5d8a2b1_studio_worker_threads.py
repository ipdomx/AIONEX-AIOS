"""Real Studio worker/PostgreSQL with blocking archive and storage threads.

Uses only the existing disposable schema fixtures and synthetic local artifacts.
Thread completion is not labelled durable resource settlement or storage safety.
"""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import threading

import pytest

from app.services import studio_worker as workers
from app.services.studio_execution_guard import GUARD_KEY

_name = "fr06d8b1_studio_execution_fixture"
_spec = importlib.util.spec_from_file_location(
    _name, Path(__file__).with_name("test_fr06c5d8a2a_studio_one_shot.py"),
)
assert _spec is not None and _spec.loader is not None
_shared = importlib.util.module_from_spec(_spec)
sys.modules[_name] = _shared
_spec.loader.exec_module(_shared)
studio_case = _shared.studio_case
execution_case = _shared.execution_case


async def _until(predicate):
    async with asyncio.timeout(8):
        while not predicate():
            await asyncio.sleep(0.002)


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["build_archive", "store_artifact"])
@pytest.mark.parametrize("late_failure", [False, True])
async def test_worker_waits_for_actual_thread_and_preserves_unresolved_owner(
    execution_case, monkeypatch, phase, late_failure,
):
    case = execution_case
    identifier = await _shared._new(case)
    claimed = await case.worker.claim_by_id(identifier)
    assert claimed is not None
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = getattr(workers, phase)
    returned_paths = []
    calls = []
    def blocking(*args, **kwargs):
        calls.append(phase)
        entered.set()
        try:
            assert release.wait(8), "test did not release the blocked function"
            if late_failure:
                raise OSError("synthetic late thread failure")
            result = original(*args, **kwargs)
            if phase == "store_artifact":
                returned_paths.append(result)
            return result
        finally:
            finished.set()
    monkeypatch.setattr(workers, phase, blocking)
    task = asyncio.create_task(case.worker.execute(*claimed))
    try:
        await _until(entered.is_set)
        response = await case.client.post(f"/studio/jobs/{identifier}/cancel")
        assert response.status_code == 200, response.text
        for index in range(3):
            task.cancel("worker-interrupted-" + str(index))
            await asyncio.sleep(0)
            assert not task.done()
        row = await _shared._row(case, identifier)
        assert row["status"] == "cancel_requested"
        assert row["completed_at"] is None
        assert row["result_metadata"][GUARD_KEY]["phase"] == "executing"
        assert row["result_metadata"][GUARD_KEY]["cleanup_verified"] is False
        assert not finished.is_set()
        # No second execution while the original thread is still active.
        await case.worker.execute(*claimed)
        assert calls == [phase]
        release.set()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await task
        assert finished.is_set()
        if late_failure:
            assert isinstance(cancelled.value.__cause__, OSError)
        row = await _shared._row(case, identifier)
        assert row["status"] == "cancel_requested" and row["completed_at"] is None
        assert row["attempts"] == 1
        assert row["result_metadata"][GUARD_KEY]["phase"] == "unresolved"
        assert row["result_metadata"][GUARD_KEY]["cleanup_verified"] is False
        assert row["error_code"] == "STUDIO_RECONCILIATION_REQUIRED"
        assert await case.worker.claim_by_id(identifier) is None
        retry = await case.client.post(f"/studio/jobs/{identifier}/retry")
        assert retry.status_code == 409
        assert calls == [phase]
        archives = list(case.root.rglob("*.zip"))
        if phase == "store_artifact" and not late_failure:
            # Retention, NOT cleanup success: a later durable reconciliation must
            # decide the disposition. This increment never deletes this output.
            assert len(returned_paths) == 1 and archives == returned_paths
            assert archives[0].is_file() and archives[0].stat().st_size > 0
        else:
            assert not archives
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
