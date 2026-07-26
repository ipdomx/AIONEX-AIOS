from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import secrets


class SessionState(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass
class MobileSession:
    session_id: str
    user_id: str
    device_id: str
    access_token: str
    created_at: datetime
    expires_at: datetime
    state: SessionState = SessionState.ACTIVE
    scopes: set[str] = field(default_factory=set)

    def is_active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if self.state is SessionState.REVOKED:
            return False
        if current >= self.expires_at:
            self.state = SessionState.EXPIRED
            return False
        return self.state is SessionState.ACTIVE


class MobileSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, MobileSession] = {}

    def create(self, user_id: str, device_id: str, ttl_minutes: int = 60, scopes: set[str] | None = None) -> MobileSession:
        if not user_id.strip() or not device_id.strip():
            raise ValueError("user_id and device_id are required")
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be positive")
        now = datetime.now(timezone.utc)
        session = MobileSession(
            session_id=secrets.token_urlsafe(18),
            user_id=user_id,
            device_id=device_id,
            access_token=secrets.token_urlsafe(32),
            created_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
            scopes=set(scopes or set()),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> MobileSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise LookupError(f"session not found: {session_id}") from exc

    def revoke(self, session_id: str) -> None:
        self.get(session_id).state = SessionState.REVOKED

    def active_for_user(self, user_id: str) -> list[MobileSession]:
        return [session for session in self._sessions.values() if session.user_id == user_id and session.is_active()]
