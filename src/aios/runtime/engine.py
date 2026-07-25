from __future__ import annotations
import hashlib, json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
from .cluster import ClusterManager
from .scheduler import IntelligentScheduler
from .models import DistributedTask, TaskState

class DistributedRuntime:
    def __init__(self, cluster:ClusterManager, state_dir:Path):
        self.cluster=cluster; self.scheduler=IntelligentScheduler(cluster); self.state_dir=state_dir; state_dir.mkdir(parents=True,exist_ok=True); self.tasks={}
    def submit(self,tenant_id:str,project_id:str,capability:str,payload:dict,priority:int=3)->DistributedTask:
        task=DistributedTask(str(uuid4()),tenant_id,project_id,capability,payload,priority)
        self.tasks[task.task_id]=task; self._persist(task); return task
    def assign(self,task_id:str)->str: return self.scheduler.assign(self.tasks[task_id])
    def checkpoint(self,task_id:str,data:dict)->None:
        task=self.tasks[task_id]; task.checkpoint=dict(data); task.state=TaskState.CHECKPOINTED; self._persist(task)
    def complete(self,task_id:str,result:dict)->None:
        task=self.tasks[task_id]; task.result=dict(result); task.state=TaskState.COMPLETED
        if task.worker_id: self.scheduler.release(task.worker_id)
        self._persist(task)
    def fail_and_requeue(self,task_id:str,error:str)->str:
        task=self.tasks[task_id]; fp=hashlib.sha256(error.encode()).hexdigest()[:16]
        task.failure_fingerprints.append(fp); task.attempts+=1
        if task.worker_id: self.scheduler.release(task.worker_id)
        task.worker_id=None; task.state=TaskState.REQUEUED; self._persist(task)
        return fp
    def resume(self,task_id:str)->DistributedTask:
        task=self.tasks[task_id]
        if task.state in {TaskState.REQUEUED,TaskState.CHECKPOINTED}: self.assign(task_id)
        return task
    def _persist(self,task:DistributedTask)->None:
        data=asdict(task)
        data['state']=task.state.value
        (self.state_dir/f'{task.task_id}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
