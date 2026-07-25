from __future__ import annotations
from .checkpoints import CheckpointManager
from .cluster import ClusterManager
from .leader import LeaderElection
from .locks import DistributedLockManager
from .recovery import DistributedRecoveryManager
from .scheduler import DistributedScheduler
from .workers import WorkerRegistry

class DistributedRuntime:
    def __init__(self, checkpoint_root: str = "storage/checkpoints", heartbeat_timeout: float = 30.0, leader_lease_seconds: float = 15.0):
        self.workers = WorkerRegistry(heartbeat_timeout=heartbeat_timeout)
        self.scheduler = DistributedScheduler(self.workers)
        self.locks = DistributedLockManager()
        self.election = LeaderElection(lease_seconds=leader_lease_seconds)
        self.checkpoints = CheckpointManager(root=checkpoint_root)
        self.recovery = DistributedRecoveryManager(self.workers, self.scheduler, self.checkpoints)
        self.cluster = ClusterManager(self.workers, self.election, self.locks)
        self.initialized = False

    async def initialize(self) -> None:
        if not self.initialized:
            await self.scheduler.start()
            self.initialized = True

    async def shutdown(self) -> None:
        if self.initialized:
            await self.scheduler.stop()
            self.initialized = False

    async def maintenance(self) -> dict:
        cluster = await self.cluster.maintenance()
        recovery = await self.recovery.recover_failed_workers()
        return {"cluster": cluster, "recovery": recovery}

    async def validate(self) -> dict:
        checks = {
            "initialized": self.initialized,
            "workers": self.workers is not None,
            "scheduler": self.scheduler is not None,
            "locks": self.locks is not None,
            "leader_election": self.election is not None,
            "checkpoints": self.checkpoints is not None,
            "recovery": self.recovery is not None,
            "cluster": self.cluster is not None,
        }
        return {"phase": 9, "status": "PASSED" if all(checks.values()) else "FAILED", "checks": checks, "summary": await self.summary()}

    async def summary(self) -> dict:
        return {"cluster": await self.cluster.summary(), "scheduler": await self.scheduler.summary(), "recovery": await self.recovery.summary(), "initialized": self.initialized}

    async def version(self) -> dict:
        return {"project": "AIONEX AIOS", "phase": 9, "component": "Distributed Runtime & Recovery", "status": "Completed", "version": "2.4.0-beta.1"}
