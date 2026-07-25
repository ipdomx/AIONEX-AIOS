from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4

class Severity(StrEnum):
    INFO='info'; ACTION_REQUIRED='action_required'; WARNING='warning'; CRITICAL='critical'; EMERGENCY='emergency'
class Channel(StrEnum):
    IN_APP='in_app'; PUSH='push'; BOT='bot'; EMAIL='email'; WHATSAPP='whatsapp'
class Audience(StrEnum):
    USER='user'; ORGANIZATION='organization'; WORKFORCE='workforce'; OWNER='owner'

@dataclass(slots=True, frozen=True)
class Notification:
    tenant_id: str
    audience: Audience
    recipient_id: str
    subject: str
    body: str
    severity: Severity=Severity.INFO
    project_id: str|None=None
    action_url: str|None=None
    metadata: dict[str,Any]=field(default_factory=dict)
    notification_id: str=field(default_factory=lambda:str(uuid4()))

@dataclass(slots=True)
class Preference:
    recipient_id: str
    allowed_channels: set[Channel]
    push_consent: bool=False
    quiet_hours: tuple[int,int]|None=None
