from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

class SessionStatus(StrEnum): REQUESTED='requested'; APPROVED='approved'; REJECTED='rejected'; ACTIVE='active'; EXPIRED='expired'

@dataclass(slots=True)
class ExpertSession:
    session_id:str; user_id:str; project:str; persona_id:str; duration_minutes:int; price:float; currency:str='USD'; status:SessionStatus=SessionStatus.REQUESTED; owner_approved_by:str|None=None; expires_at:str|None=None

class PricingPolicy:
    ROLE={'project-staff':0,'specialist':80,'senior-engineer':150,'manager':220,'chief-engineer':400}
    COMPLEXITY={'small':1.0,'medium':1.5,'large':2.2,'critical':3.0}
    def quote(self,persona_id,project_size,minutes,priority=1.0):
        rate=self.ROLE[persona_id]*self.COMPLEXITY.get(project_size,1.5)*priority
        return round(rate*max(minutes,1)/60,2)

class SessionAccessController:
    def __init__(self, db, owner_id='owner'):
        self.db=db; self.owner_id=owner_id; self.pricing=PricingPolicy()
    def request(self,user_id,project,persona_id,project_size,minutes,*,free_used=0,free_limit=0):
        free=persona_id=='project-staff' and free_used<free_limit
        price=0.0 if free else self.pricing.quote(persona_id,project_size,minutes)
        s=ExpertSession(str(uuid4()),user_id,project,persona_id,minutes,price)
        with self.db.connect() as c: c.execute('INSERT INTO expert_sessions(session_id,user_id,project,persona_id,duration_minutes,price,currency,status) VALUES (?,?,?,?,?,?,?,?)',(s.session_id,s.user_id,s.project,s.persona_id,s.duration_minutes,s.price,s.currency,s.status.value))
        return s
    def approve(self,session_id,approved_by):
        if approved_by!=self.owner_id: raise PermissionError('only owner may approve meetings')
        expiry=(datetime.now(UTC)+timedelta(minutes=60)).isoformat()
        with self.db.connect() as c: c.execute('UPDATE expert_sessions SET status=?, owner_approved_by=?, approved_at=CURRENT_TIMESTAMP, expires_at=? WHERE session_id=?',(SessionStatus.APPROVED.value,approved_by,expiry,session_id))
        return {'session_id':session_id,'status':SessionStatus.APPROVED.value,'approved_by':approved_by,'expires_at':expiry}
