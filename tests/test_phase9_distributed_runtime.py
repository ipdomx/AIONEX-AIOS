import asyncio
import time
from pathlib import Path

from aios.distributed import (
    DistributedRuntime,
    WorkerNode,
    WorkerStatus,
    TaskStatus,
)


def run(coro):
    return asyncio.run(coro)


def test_phase9_runtime_validation(tmp_path: Path):
    runtime = DistributedRuntime(checkpoint_root=str(tmp_path / "checkpoints"))
    run(runtime.initialize())
    result = run(runtime.validate())
    assert result["phase"] == 9
    assert result["status"] == "PASSED"
    run(runtime.shutdown())


def test_worker_registration_selection_and_expiry():
    runtime = DistributedRuntime(heartbeat_timeout=0.01)
    worker = WorkerNode("worker-1", "host-1", {"python"}, max_concurrency=2)
    run(runtime.workers.register(worker))
    selected = run(runtime.workers.select("python"))
    assert selected.worker_id == "worker-1"
    runtime.workers.workers["worker-1"].last_heartbeat = time.time() - 1
    expired = run(runtime.workers.expire_stale())
    assert expired == ["worker-1"]
    assert runtime.workers.workers["worker-1"].status == WorkerStatus.OFFLINE


def test_scheduler_success_and_retry(tmp_path: Path):
    runtime = DistributedRuntime(checkpoint_root=str(tmp_path / "checkpoints"))
    run(runtime.workers.register(WorkerNode("worker-1", "host-1", {"jobs"}, max_concurrency=1)))

    async def success(task):
        return task.payload["value"] * 2

    attempts = {"count": 0}

    async def flaky(task):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary")
        return "ok"

    run(runtime.scheduler.register_handler("success", success))
    run(runtime.scheduler.register_handler("flaky", flaky))
    task1 = run(runtime.scheduler.submit("success", {"value": 5}, "jobs"))
    task2 = run(runtime.scheduler.submit("flaky", {}, "jobs", max_retries=1))
    run(runtime.scheduler.run_once())
    run(runtime.scheduler.run_once())
    run(runtime.scheduler.run_once())
    assert runtime.scheduler.tasks[task1.task_id].status == TaskStatus.SUCCEEDED
    assert runtime.scheduler.tasks[task1.task_id].result == 10
    assert runtime.scheduler.tasks[task2.task_id].status == TaskStatus.SUCCEEDED


def test_distributed_lock_lifecycle():
    runtime = DistributedRuntime()
    lease = run(runtime.locks.acquire("resource", "node-a", ttl_seconds=1))
    assert lease is not None
    assert run(runtime.locks.acquire("resource", "node-b", ttl_seconds=1)) is None
    assert run(runtime.locks.is_owner("resource", lease.token))
    renewed = run(runtime.locks.renew("resource", lease.token, ttl_seconds=2))
    assert renewed.expires_at > lease.acquired_at
    assert run(runtime.locks.release("resource", lease.token))


def test_leader_election_and_failover():
    runtime = DistributedRuntime(leader_lease_seconds=0.01)
    assert run(runtime.election.campaign("node-b", priority=20)) == "node-b"
    assert run(runtime.election.campaign("node-a", priority=10)) == "node-b"
    run(runtime.election.resign("node-b"))
    assert run(runtime.election.summary())["leader_id"] == "node-a"


def test_checkpoint_integrity_and_pruning(tmp_path: Path):
    runtime = DistributedRuntime(checkpoint_root=str(tmp_path / "checkpoints"))
    first = run(runtime.checkpoints.save("task-1", {"step": 1}))
    second = run(runtime.checkpoints.save("task-1", {"step": 2}))
    payload = run(runtime.checkpoints.load(second.checkpoint_id))
    assert payload["state"]["step"] == 2
    assert run(runtime.checkpoints.prune("task-1", keep=1)) == 1
    assert not Path(first.path).exists()


def test_recovery_requeues_failed_worker_task(tmp_path: Path):
    runtime = DistributedRuntime(checkpoint_root=str(tmp_path / "checkpoints"))
    worker = WorkerNode("worker-1", "host-1", {"jobs"})
    run(runtime.workers.register(worker))
    task = run(runtime.scheduler.submit("missing", {}, "jobs"))
    task.assigned_worker = "worker-1"
    task.status = TaskStatus.RUNNING
    run(runtime.workers.set_status("worker-1", WorkerStatus.FAILED))
    operations = run(runtime.recovery.recover_failed_workers())
    assert operations[0]["status"] == "REQUEUED"
    assert task.status == TaskStatus.PENDING
