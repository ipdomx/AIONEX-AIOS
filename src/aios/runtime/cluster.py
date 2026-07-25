from __future__ import annotations
from .models import Worker, WorkerState

class ClusterManager:
    def __init__(self): self._workers: dict[str, Worker]={}
    def register(self, worker: Worker)->None: self._workers[worker.worker_id]=worker
    def get(self, worker_id:str)->Worker: return self._workers[worker_id]
    def list(self, tenant_id:str|None=None)->tuple[Worker,...]:
        items=self._workers.values()
        if tenant_id is not None: items=(w for w in items if w.tenant_id==tenant_id)
        return tuple(items)
    def heartbeat(self,worker_id:str,state:WorkerState=WorkerState.ONLINE)->None: self._workers[worker_id].state=state
    def available(self,tenant_id:str,capability:str)->tuple[Worker,...]:
        return tuple(w for w in self._workers.values() if w.tenant_id==tenant_id and capability in w.capabilities and w.state==WorkerState.ONLINE)
