from __future__ import annotations
from collections import defaultdict
from .models import Notification, Preference, Channel, Severity, Audience

class NotificationPolicyError(PermissionError): pass

class NotificationRouter:
    def __init__(self,owner_id:str):
        self.owner_id=owner_id; self.preferences={}; self.outbox=defaultdict(list); self.audit=[]
    def set_preference(self,pref:Preference)->None: self.preferences[pref.recipient_id]=pref
    def _channels(self,n:Notification)->set[Channel]:
        pref=self.preferences.get(n.recipient_id,Preference(n.recipient_id,{Channel.IN_APP}))
        channels=set(pref.allowed_channels)
        if not pref.push_consent: channels.discard(Channel.PUSH)
        if Channel.WHATSAPP in channels and (n.audience!=Audience.OWNER or n.recipient_id!=self.owner_id):
            channels.discard(Channel.WHATSAPP)
        if n.severity in {Severity.CRITICAL,Severity.EMERGENCY} and n.audience==Audience.OWNER:
            channels.update({Channel.IN_APP,Channel.EMAIL,Channel.BOT})
            if n.recipient_id==self.owner_id: channels.add(Channel.WHATSAPP)
        return channels
    def route(self,n:Notification)->tuple[Channel,...]:
        if n.audience==Audience.OWNER and n.recipient_id!=self.owner_id: raise NotificationPolicyError('owner-audience-recipient-mismatch')
        channels=tuple(sorted(self._channels(n),key=lambda c:c.value))
        for channel in channels: self.outbox[channel].append(n)
        self.audit.append({'notification_id':n.notification_id,'recipient':n.recipient_id,'channels':[c.value for c in channels],'severity':n.severity.value})
        return channels
