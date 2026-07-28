from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class AndroidSessionState(str, Enum):
    SIGNED_OUT = "signed_out"
    AUTHENTICATING = "authenticating"
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(slots=True)
class AndroidDevice:
    device_id: str
    user_id: str
    owner_id: str
    model: str
    os_version: str
    app_version: str
    push_token: str | None = None
    registered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked: bool = False


@dataclass(slots=True)
class AndroidSession:
    session_id: str
    user_id: str
    owner_id: str
    device_id: str
    access_token: str
    refresh_token: str
    state: AndroidSessionState = AndroidSessionState.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None


@dataclass(slots=True)
class AndroidProjectSummary:
    project_id: str
    name: str
    status: str
    progress_percent: float
    open_tasks: int
    open_incidents: int
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(slots=True)
class AndroidNotificationItem:
    notification_id: str
    title: str
    body: str
    priority: str
    acknowledged: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, object] = field(default_factory=dict)
