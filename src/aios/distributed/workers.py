from __future__ import annotations
import asyncio, time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

class WorkerStatus(str, Enum):
    STARTING="STARTING"; ONLINE="ONLINE"; DRAINING="DRAINING"; OFFLINE="OFFLINE"; FAILED="FAILED"

@dataclass
class WorkerNode:
    worker_id: str
    hostname: str
    capabilities: set[str] = field(default_factory=set)
    status: WorkerStatus = WorkerStatus.STARTING
    current_load: int = 0
    max_concurrency: int = 1
    last_heartbeat: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

class WorkerRegistry:
    def __init__(self, heartbeat_timeout: float = 30.0):
        self.heartbeat_timeout = heartbeat_timeout
        self.workers: Dict[str, WorkerNode] = {}
        self.lock = asyncio.Lock()

    async def register(self, worker: WorkerNode) -> WorkerNode:
        async with self.lock:
            worker.status = WorkerStatus.ONLINE
            worker.last_heartbeat = time.time()
            self.workers[worker.worker_id] = worker
            return worker

    async def heartbeat(self, worker_id: str, current_load: Optional[int] = None) -> WorkerNode:
        async with self.lock:
            worker = self.workers[worker_id]
            worker.last_heartbeat = time.time()
            if current_load is not None:
                worker.current_load = max(0, int(current_load))
            if worker.status not in {WorkerStatus.DRAINING, WorkerStatus.FAILED}:
                worker.status = WorkerStatus.ONLINE
            return worker

    async def set_status(self, worker_id: str, status: WorkerStatus) -> WorkerNode:
        async with self.lock:
            self.workers[worker_id].status = status
            return self.workers[worker_id]

    async def expire_stale(self) -> list[str]:
        expired, now = [], time.time()
        async with self.lock:
            for worker in self.workers.values():
                if worker.status == WorkerStatus.ONLINE and now-worker.last_heartbeat > self.heartbeat_timeout:
                    worker.status = WorkerStatus.OFFLINE
                    expired.append(worker.worker_id)
        return expired

    async def select(self, capability: Optional[str] = None) -> Optional[WorkerNode]:
        async with self.lock:
            candidates = [w for w in self.workers.values() if w.status == WorkerStatus.ONLINE and w.current_load < w.max_concurrency and (capability is None or capability in w.capabilities)]
            return min(candidates, key=lambda w: (w.current_load / max(1, w.max_concurrency), w.worker_id)) if candidates else None

    async def summary(self) -> dict:
        async with self.lock:
            values = list(self.workers.values())
            return {"total": len(values), "online": sum(w.status == WorkerStatus.ONLINE for w in values), "offline": sum(w.status == WorkerStatus.OFFLINE for w in values), "failed": sum(w.status == WorkerStatus.FAILED for w in values), "draining": sum(w.status == WorkerStatus.DRAINING for w in values)}
