from __future__ import annotations

from datetime import datetime, timezone

from .models import RoleSessionRequest, SessionStatus


class RoleSessionService:
    def __init__(self) -> None:
        self._sessions: dict[str, RoleSessionRequest] = {}

    def submit(self, request: RoleSessionRequest) -> RoleSessionRequest:
        if request.session_id in self._sessions:
            raise ValueError(f"duplicate session request: {request.session_id}")
        request.status = SessionStatus.PENDING_OWNER_APPROVAL
        request.updated_at = datetime.now(timezone.utc)
        self._sessions[request.session_id] = request
        return request

    def approve(
        self,
        session_id: str,
        *,
        owner_id: str,
        approved_minutes: int,
        price_minor: int,
        starts_at: datetime | None = None,
    ) -> RoleSessionRequest:
        session = self._sessions[session_id]
        if session.status is not SessionStatus.PENDING_OWNER_APPROVAL:
            raise RuntimeError("session is not awaiting owner approval")
        if approved_minutes <= 0:
            raise ValueError("approved_minutes must be positive")
        if price_minor < 0:
            raise ValueError("price_minor cannot be negative")
        session.owner_id = owner_id
        session.approved_minutes = approved_minutes
        session.price_minor = price_minor
        session.starts_at = starts_at
        session.status = SessionStatus.SCHEDULED if starts_at else SessionStatus.APPROVED
        session.updated_at = datetime.now(timezone.utc)
        return session

    def reject(self, session_id: str, *, owner_id: str) -> RoleSessionRequest:
        session = self._sessions[session_id]
        if session.status is not SessionStatus.PENDING_OWNER_APPROVAL:
            raise RuntimeError("session is not awaiting owner approval")
        session.owner_id = owner_id
        session.status = SessionStatus.REJECTED
        session.updated_at = datetime.now(timezone.utc)
        return session

    def start(self, session_id: str) -> RoleSessionRequest:
        session = self._sessions[session_id]
        if session.status not in {SessionStatus.APPROVED, SessionStatus.SCHEDULED}:
            raise RuntimeError("session cannot be started")
        session.status = SessionStatus.ACTIVE
        session.updated_at = datetime.now(timezone.utc)
        return session

    def complete(self, session_id: str) -> RoleSessionRequest:
        session = self._sessions[session_id]
        if session.status is not SessionStatus.ACTIVE:
            raise RuntimeError("only active sessions can be completed")
        session.status = SessionStatus.COMPLETED
        session.updated_at = datetime.now(timezone.utc)
        return session

    def get(self, session_id: str) -> RoleSessionRequest:
        return self._sessions[session_id]

    def list_for_user(self, user_id: str) -> list[RoleSessionRequest]:
        return sorted(
            (session for session in self._sessions.values() if session.user_id == user_id),
            key=lambda session: session.created_at,
            reverse=True,
        )
