from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import secrets


class DashboardSessionState(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


@dataclass
class DashboardSession:
    session_id: str
    subject_id: str
    dashboard_id: str
    token_id: str
    created_at: datetime
    expires_at: datetime
    state: DashboardSessionState = DashboardSessionState.ACTIVE
    metadata: dict[str, str] = field(default_factory=dict)

    def is_active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if self.state is DashboardSessionState.REVOKED:
            return False
        if current >= self.expires_at:
            self.state = DashboardSessionState.EXPIRED
            return False
        return self.state is DashboardSessionState.ACTIVE


class DashboardSessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, DashboardSession] = {}

    def create(
        self,
        subject_id: str,
        dashboard_id: str,
        token_id: str,
        ttl_minutes: int = 30,
        metadata: dict[str, str] | None = None,
    ) -> DashboardSession:
        if not subject_id.strip() or not dashboard_id.strip() or not token_id.strip():
            raise ValueError("subject_id, dashboard_id, and token_id are required")
        if ttl_minutes <= 0:
            raise ValueError("ttl_minutes must be positive")
        now = datetime.now(timezone.utc)
        session = DashboardSession(
            session_id=secrets.token_urlsafe(18),
            subject_id=subject_id,
            dashboard_id=dashboard_id,
            token_id=token_id,
            created_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
            metadata=dict(metadata or {}),
        )
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> DashboardSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise LookupError(f"dashboard session not found: {session_id}") from exc

    def revoke(self, session_id: str) -> None:
        self.get(session_id).state = DashboardSessionState.REVOKED

    def active_for_subject(self, subject_id: str) -> list[DashboardSession]:
        return [session for session in self._sessions.values() if session.subject_id == subject_id and session.is_active()]
