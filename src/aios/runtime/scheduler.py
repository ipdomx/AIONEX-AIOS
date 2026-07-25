from __future__ import annotations
from .cluster import ClusterManager
from .models import DistributedTask, WorkerState, TaskState

class IntelligentScheduler:
    def __init__(self, cluster:ClusterManager): self.cluster=cluster
    def assign(self,task:DistributedTask)->str:
        workers=self.cluster.available(task.tenant_id,task.capability)
        if not workers: raise RuntimeError('no-compatible-worker')
        worker=max(workers,key=lambda w:(w.trust_score, w.cpu_cores, w.memory_mb, -w.cost_per_hour))
        worker.state=WorkerState.BUSY; worker.current_task=task.task_id
        task.worker_id=worker.worker_id; task.state=TaskState.ASSIGNED
        return worker.worker_id
    def release(self,worker_id:str)->None:
        worker=self.cluster.get(worker_id); worker.state=WorkerState.ONLINE; worker.current_task=None
