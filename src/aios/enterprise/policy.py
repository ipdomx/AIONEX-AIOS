from __future__ import annotations
from .models import PolicyDecision

class PolicyEngine:
    def evaluate(self,*,actor_role:str,action:str,environment:str='development',owner_approved:bool=False,cost:float=0,budget:float|None=None)->PolicyDecision:
        reasons=[]; obligations=[]
        if budget is not None and cost>budget: reasons.append('budget_exceeded')
        high_risk=environment=='production' or action in {'release','secret.read','meeting.approve','workflow.override'}
        if high_risk and actor_role!='owner' and not owner_approved: reasons.append('owner_approval_required')
        if action=='meeting.approve' and actor_role!='owner': reasons.append('owner_only_action')
        if environment=='production': obligations.extend(('audit_required','rollback_required'))
        return PolicyDecision(not reasons,tuple(dict.fromkeys(reasons)),tuple(obligations))
