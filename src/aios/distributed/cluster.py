from __future__ import annotations
from .leader import LeaderElection
from .locks import DistributedLockManager
from .workers import WorkerRegistry, WorkerNode, WorkerStatus

class ClusterManager:
    def __init__(self, workers: WorkerRegistry, election: LeaderElection, locks: DistributedLockManager):
        self.workers = workers
        self.election = election
        self.locks = locks

    async def join(self, worker_id: str, hostname: str, capabilities=None, max_concurrency: int = 1, priority: int = 100):
        worker = WorkerNode(worker_id=worker_id, hostname=hostname, capabilities=set(capabilities or []), max_concurrency=max_concurrency)
        await self.workers.register(worker)
        await self.election.campaign(worker_id, priority)
        return worker

    async def leave(self, worker_id: str) -> None:
        if worker_id in self.workers.workers:
            await self.workers.set_status(worker_id, WorkerStatus.OFFLINE)
        await self.election.resign(worker_id)

    async def heartbeat(self, worker_id: str, current_load: int = 0) -> dict:
        worker = await self.workers.heartbeat(worker_id, current_load)
        leader = await self.election.heartbeat(worker_id)
        return {"worker_id": worker.worker_id, "status": worker.status.value, "leader": leader}

    async def maintenance(self) -> dict:
        expired = await self.workers.expire_stale()
        recovered_locks = await self.locks.cleanup_expired()
        for worker_id in expired:
            await self.election.resign(worker_id)
        return {"expired_workers": expired, "expired_locks": recovered_locks}

    async def summary(self) -> dict:
        return {"workers": await self.workers.summary(), "leadership": await self.election.summary()}
