from __future__ import annotations
import json
from pathlib import Path
from .models import Notification, Audience, Severity, Channel, Preference
from .router import NotificationRouter

class NotificationCenter:
    def __init__(self,owner_id:str,audit_path:Path):
        self.owner_id=owner_id; self.router=NotificationRouter(owner_id); self.audit_path=audit_path; audit_path.parent.mkdir(parents=True,exist_ok=True)
    def configure(self,recipient_id:str,channels:set[Channel],push_consent:bool=False)->None:
        self.router.set_preference(Preference(recipient_id,channels,push_consent))
    def notify(self,n:Notification)->tuple[Channel,...]:
        channels=self.router.route(n)
        record={'id':n.notification_id,'tenant':n.tenant_id,'audience':n.audience.value,'recipient':n.recipient_id,'project':n.project_id,'subject':n.subject,'severity':n.severity.value,'channels':[c.value for c in channels]}
        with self.audit_path.open('a',encoding='utf-8') as f: f.write(json.dumps(record,ensure_ascii=False)+'\n')
        return channels
    def project_question(self,tenant_id:str,user_id:str,project_id:str,question:str)->tuple[Channel,...]:
        return self.notify(Notification(tenant_id,Audience.USER,user_id,'Project input required',question,Severity.ACTION_REQUIRED,project_id))
    def owner_event(self,tenant_id:str,subject:str,body:str,severity:Severity=Severity.INFO,project_id:str|None=None)->tuple[Channel,...]:
        return self.notify(Notification(tenant_id,Audience.OWNER,self.owner_id,subject,body,severity,project_id))
    def workforce_event(self,tenant_id:str,recipient_id:str,subject:str,body:str,project_id:str|None=None)->tuple[Channel,...]:
        channels=self.notify(Notification(tenant_id,Audience.WORKFORCE,recipient_id,subject,body,Severity.INFO,project_id))
        self.owner_event(tenant_id,f'Workforce activity: {subject}',f'{recipient_id}: {body}',Severity.INFO,project_id)
        return channels
