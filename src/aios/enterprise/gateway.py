from __future__ import annotations
import time
from collections import defaultdict,deque

class APIGateway:
    def __init__(self,policy,tenant_context,limit_per_minute:int=60):
        self.policy=policy; self.tenants=tenant_context; self.limit=limit_per_minute; self._calls=defaultdict(deque)
    def authorize(self,*,tenant_id:str,subject_id:str,role:str,action:str,environment:str='development',owner_approved:bool=False):
        self.tenants.require(tenant_id,subject_id)
        now=time.time(); q=self._calls[(tenant_id,subject_id)]
        while q and q[0]<now-60:q.popleft()
        if len(q)>=self.limit: raise RuntimeError('rate_limit_exceeded')
        decision=self.policy.evaluate(actor_role=role,action=action,environment=environment,owner_approved=owner_approved)
        if not decision.allowed: raise PermissionError(','.join(decision.reasons))
        q.append(now); return decision
