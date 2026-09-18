"""Actual executor/thread lifecycle tests, independent of DB/provider access."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import threading

import pytest

from app.services.studio_thread_runtime import StudioThreadUncertain, joined_studio_thread


async def _until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.002)


@pytest.mark.asyncio
async def test_result_arguments_and_context_are_preserved():
    context = ContextVar("studio_test_context", default="missing")
    context.set("synthetic-scope")
    parent_thread = threading.get_ident()
    def function(number, *, suffix):
        return number, suffix, context.get(), threading.get_ident()
    number, suffix, captured, worker_thread = await joined_studio_thread(function, 42, suffix="archive")
    assert (number, suffix, captured) == (42, "archive", "synthetic-scope")
    assert worker_thread != parent_thread


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [ValueError, OSError, RuntimeError])
async def test_function_failure_is_not_success(error):
    def function():
        raise error("synthetic function failure")
    with pytest.raises(error, match="synthetic function failure"):
        await joined_studio_thread(function)


@pytest.mark.asyncio
@pytest.mark.parametrize("repetitions", [1, 3, 16])
async def test_repeated_caller_cancel_waits_for_real_file_writer(tmp_path, repetitions):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    destination = tmp_path / "thread-result.bin"
    def function():
        entered.set()
        try:
            assert release.wait(5), "test release not received"
            destination.write_bytes(b"complete synthetic artifact")
            return destination
        finally:
            finished.set()
    task = asyncio.create_task(joined_studio_thread(function))
    try:
        await _until(entered.is_set)
        for index in range(repetitions):
            task.cancel("cancel-" + str(index))
            await asyncio.sleep(0)
            assert not task.done()
        assert not finished.is_set() and not destination.exists()
        release.set()
        with pytest.raises(asyncio.CancelledError, match="cancel-0"):
            await task
        assert finished.is_set()
        assert destination.read_bytes() == b"complete synthetic artifact"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError, ValueError])
async def test_cancellation_retains_post_cancel_function_failure_as_cause(error):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def function():
        entered.set()
        try:
            assert release.wait(5)
            raise error("late storage failure")
        finally:
            finished.set()
    task = asyncio.create_task(joined_studio_thread(function))
    try:
        await _until(entered.is_set)
        task.cancel("retain cancellation")
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError) as failure:
            await task
        assert isinstance(failure.value.__cause__, error)
        assert str(failure.value.__cause__) == "late storage failure"
        assert finished.is_set()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_timeout_does_not_claim_thread_completion(tmp_path):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    output = tmp_path / "timeout-result.bin"
    def function():
        entered.set()
        try:
            assert release.wait(5)
            output.write_bytes(b"late-but-complete")
        finally:
            finished.set()
    async def bounded():
        async with asyncio.timeout(0.05):
            await joined_studio_thread(function)
    task = asyncio.create_task(bounded())
    try:
        await _until(entered.is_set)
        await _until(lambda: task.cancelling() > 0)
        assert not task.done() and not finished.is_set()
        release.set()
        with pytest.raises(TimeoutError):
            await task
        assert finished.is_set() and output.read_bytes() == b"late-but-complete"
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_before_entry_does_not_submit_a_function():
    observed = []
    task = asyncio.create_task(joined_studio_thread(lambda: observed.append("unexpected")))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert observed == []


@pytest.mark.asyncio
async def test_independently_cancelled_executor_future_is_explicitly_uncertain(monkeypatch):
    # Deliberately synthetic future, NOT proof that a running thread was stopped.
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    monkeypatch.setattr(loop, "run_in_executor", lambda *args: future)
    task = asyncio.create_task(joined_studio_thread(lambda: "unused"))
    await asyncio.sleep(0)
    future.cancel()
    with pytest.raises(StudioThreadUncertain, match="unverified"):
        await task


@pytest.mark.asyncio
async def test_already_finished_executor_failure_is_observed(monkeypatch):
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    future.set_exception(ValueError("already finished"))
    monkeypatch.setattr(loop, "run_in_executor", lambda *args: future)
    with pytest.raises(ValueError, match="already finished"):
        await joined_studio_thread(lambda: "unused")


@pytest.mark.asyncio
async def test_parallel_functions_are_all_joined_before_cancelled_callers_return():
    release = threading.Event()
    entered = [threading.Event() for _ in range(8)]
    finished = [threading.Event() for _ in entered]
    def function(index):
        entered[index].set()
        try:
            assert release.wait(5)
            return index
        finally:
            finished[index].set()
    tasks = [asyncio.create_task(joined_studio_thread(function, index)) for index in range(8)]
    try:
        await _until(lambda: all(event.is_set() for event in entered))
        for task in tasks:
            task.cancel()
        await asyncio.sleep(0)
        assert all(not task.done() for task in tasks)
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(value, asyncio.CancelledError) for value in results)
        assert all(event.is_set() for event in finished)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
