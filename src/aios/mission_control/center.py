from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(slots=True)
class MissionSnapshot:
    projects:int; workers:int; active_tasks:int; pending_approvals:int; alerts:int

class MissionControl:
    def __init__(self,owner_id:str,cluster,runtime,notifications):
        self.owner_id=owner_id; self.cluster=cluster; self.runtime=runtime; self.notifications=notifications; self.approvals={}; self.activity=[]
    def request_approval(self,approval_id:str,summary:str,requested_by:str)->None:
        self.approvals[approval_id]={'summary':summary,'requested_by':requested_by,'status':'pending'}
    def decide(self,approval_id:str,actor_id:str,approved:bool)->None:
        if actor_id!=self.owner_id: raise PermissionError('owner-approval-required')
        self.approvals[approval_id]['status']='approved' if approved else 'rejected'; self.approvals[approval_id]['decided_by']=actor_id
    def record(self,event:str,details:dict[str,Any])->None: self.activity.append({'event':event,'details':details})
    def snapshot(self)->MissionSnapshot:
        active=sum(1 for t in self.runtime.tasks.values() if t.state.value not in {'completed','failed'})
        pending=sum(1 for a in self.approvals.values() if a['status']=='pending')
        return MissionSnapshot(0,len(self.cluster.list()),active,pending,len(self.notifications.router.outbox))
