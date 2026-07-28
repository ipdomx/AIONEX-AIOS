from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass(slots=True)
class IOSSession:
    session_id: str
    owner_id: str
    device_id: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked: bool = False


class IOSSessionService:
    def __init__(self, access_ttl: timedelta = timedelta(hours=1)) -> None:
        self._sessions: dict[str, IOSSession] = {}
        self._access_ttl = access_ttl

    def create(self, *, session_id: str, owner_id: str, device_id: str) -> IOSSession:
        now = datetime.now(timezone.utc)
        session = IOSSession(
            session_id=session_id,
            owner_id=owner_id,
            device_id=device_id,
            access_token=secrets.token_urlsafe(32),
            refresh_token=secrets.token_urlsafe(48),
            expires_at=now + self._access_ttl,
        )
        self._sessions[session_id] = session
        return session

    def refresh(self, session_id: str, owner_id: str, refresh_token: str) -> IOSSession:
        session = self._sessions[session_id]
        if session.owner_id != owner_id:
            raise PermissionError("session belongs to another owner")
        if session.revoked or not secrets.compare_digest(session.refresh_token, refresh_token):
            raise PermissionError("invalid session refresh")
        session.access_token = secrets.token_urlsafe(32)
        session.refresh_token = secrets.token_urlsafe(48)
        session.expires_at = datetime.now(timezone.utc) + self._access_ttl
        return session

    def revoke(self, session_id: str, owner_id: str) -> None:
        session = self._sessions[session_id]
        if session.owner_id != owner_id:
            raise PermissionError("session belongs to another owner")
        session.revoked = True
