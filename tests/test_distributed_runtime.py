from datetime import timedelta

import pytest

from aios.distributed_runtime import (
    InMemoryTaskQueue,
    RuntimeScheduler,
    TaskSpec,
    TaskState,
    WorkerDescriptor,
    WorkerRegistry,
    WorkerState,
)
from aios.distributed_runtime.models import utcnow


def build_runtime():
    queue = InMemoryTaskQueue()
    registry = WorkerRegistry()
    scheduler = RuntimeScheduler(queue, registry)
    return queue, registry, scheduler


def test_idempotent_submission_returns_existing_task():
    queue, _, scheduler = build_runtime()
    first = scheduler.submit(TaskSpec(kind="build", payload={}, idempotency_key="project-1"))
    second = scheduler.submit(TaskSpec(kind="build", payload={}, idempotency_key="project-1"))
    assert first.task_id == second.task_id
    assert queue.get(first.task_id).state is TaskState.PENDING


def test_scheduler_assigns_capable_least_loaded_worker():
    queue, registry, scheduler = build_runtime()
    registry.register(WorkerDescriptor("worker-b", frozenset({"python"}), max_concurrency=2, active_tasks=1))
    registry.register(WorkerDescriptor("worker-a", frozenset({"python", "docker"}), max_concurrency=4))
    task = scheduler.submit(TaskSpec(kind="container-build", payload={}, required_capabilities=frozenset({"docker"})))
    assignment = scheduler.assign_next()
    assert assignment is not None
    assert assignment.task.task_id == task.task_id
    assert assignment.worker.worker_id == "worker-a"
    assert assignment.task.state is TaskState.LEASED


def test_failure_requeues_until_attempt_limit():
    queue, registry, scheduler = build_runtime()
    registry.register(WorkerDescriptor("worker-1", frozenset()))
    task = scheduler.submit(TaskSpec(kind="job", payload={}, max_attempts=2))
    first = scheduler.assign_next()
    assert first is not None
    scheduler.fail(task.task_id, "worker-1", "temporary")
    assert task.state is TaskState.PENDING
    second = scheduler.assign_next()
    assert second is not None
    scheduler.fail(task.task_id, "worker-1", "permanent")
    assert task.state is TaskState.FAILED
    assert task.error == "permanent"


def test_expired_lease_is_requeued():
    queue, registry, scheduler = build_runtime()
    registry.register(WorkerDescriptor("worker-1", frozenset()))
    task = scheduler.submit(TaskSpec(kind="job", payload={}))
    assignment = scheduler.assign_next()
    assert assignment is not None
    task.lease_expires_at = utcnow() - timedelta(seconds=1)
    assert queue.requeue_expired() == 1
    assert task.state is TaskState.PENDING
    assert task.leased_by is None


def test_registry_expires_stale_worker():
    registry = WorkerRegistry()
    worker = registry.register(WorkerDescriptor("worker-1", frozenset()))
    worker.last_heartbeat_at = utcnow() - timedelta(seconds=90)
    assert registry.expire_stale(60) == ["worker-1"]
    assert worker.state is WorkerState.OFFLINE


def test_worker_cannot_complete_foreign_lease():
    queue, registry, scheduler = build_runtime()
    registry.register(WorkerDescriptor("worker-1", frozenset()))
    task = scheduler.submit(TaskSpec(kind="job", payload={}))
    scheduler.assign_next()
    with pytest.raises(PermissionError):
        queue.complete(task.task_id, "worker-2")
