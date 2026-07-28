from datetime import datetime, timedelta, timezone

from aios.distributed_runtime.checkpoints import CheckpointStore
from aios.distributed_runtime.health import HealthManager, HealthState
from aios.distributed_runtime.locks import DistributedLockManager


def test_checkpoint_sequences_and_latest():
    store = CheckpointStore()
    first = store.save(task_id="task-1", worker_id="worker-1", state={"step": 1})
    second = store.save(task_id="task-1", worker_id="worker-1", state={"step": 2})
    assert first.sequence == 1
    assert second.sequence == 2
    assert store.latest("task-1") == second


def test_health_manager_detects_stale_and_saturated_workers():
    manager = HealthManager(stale_after=timedelta(seconds=30))
    now = datetime.now(timezone.utc)
    stale = manager.record(
        worker_id="stale",
        heartbeat_at=now - timedelta(seconds=31),
        active_tasks=0,
        capacity=2,
        now=now,
    )
    saturated = manager.record(
        worker_id="busy",
        heartbeat_at=now,
        active_tasks=2,
        capacity=2,
        now=now,
    )
    assert stale.state is HealthState.UNHEALTHY
    assert saturated.state is HealthState.DEGRADED
    assert manager.cluster_ready()


def test_distributed_lock_exclusion_renewal_and_release():
    locks = DistributedLockManager()
    lease = locks.acquire(name="project:1", owner_id="worker-1", ttl=timedelta(seconds=10))
    assert lease is not None
    assert locks.acquire(name="project:1", owner_id="worker-2", ttl=timedelta(seconds=10)) is None
    renewed = locks.renew(token=lease.token, ttl=timedelta(seconds=30))
    assert renewed.expires_at > lease.expires_at
    assert locks.release(token=lease.token)
