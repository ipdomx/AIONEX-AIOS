"""Revocable event-stream sockets; no token or principal is persisted or logged.

Authorization is refreshed before every outbound event and periodically while
idle. A frame already admitted by a successful check is not retroactively
recalled. The fixed I/O bounds prevent an unresponsive peer retaining the local
connection or an unbounded authentication operation.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthService, UserRecord, auth_service

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
AUTHORIZATION_TIMEOUT_SECONDS = 3.0
SEND_TIMEOUT_SECONDS = 3.0
IDLE_REVALIDATION_SECONDS = 5.0
MAX_CONTROL_MESSAGE_CHARACTERS = 1024


class StreamAuthorizationLost(RuntimeError):
    """The current socket is no longer authorized; contains no private details."""


@dataclass(frozen=True, slots=True)
class StreamPrincipal:
    user_id: str
    organization_id: str
    auth_version: int
    role: str
    plan: str
    permissions: tuple[str, ...]

    @classmethod
    def from_user(cls, user: UserRecord) -> StreamPrincipal:
        return cls(user.id, user.organization_id, user.auth_version, user.role,
                   user.organization_plan, tuple(sorted(set(user.permissions))))


class AuthorizedRealtimeSocket:
    """The only socket object enrolled in the tenant event hub by the route."""

    def __init__(self, websocket: WebSocket, credential: str,
                 session_factory: SessionFactory, *, authentication: AuthService = auth_service) -> None:
        self._websocket = websocket
        self._credential = credential
        self._session_factory = session_factory
        self._authentication = authentication
        self._principal: StreamPrincipal | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def principal(self) -> StreamPrincipal:
        if self._principal is None:
            raise StreamAuthorizationLost("Stream authentication is required")
        return self._principal

    @property
    def closed(self) -> bool:
        return self._closed

    async def _close_locked(self, code: int) -> None:
        if self._closed:
            return
        self._closed = True
        self._credential = ""
        try:
            async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                await self._websocket.close(code=code)
        except Exception:
            # The peer may already be disconnected. Never log a query-string JWT.
            return

    async def close(self, code: int = 1000) -> None:
        async with self._lock:
            await self._close_locked(code)

    async def _validate_locked(self) -> StreamPrincipal:
        if self._closed:
            raise StreamAuthorizationLost("Stream authorization ended")
        try:
            async with asyncio.timeout(AUTHORIZATION_TIMEOUT_SECONDS):
                claims = await self._authentication.decode_access_token(self._credential)
                subject = claims.get("sub")
                if not isinstance(subject, str) or not subject:
                    raise PermissionError("Invalid stream subject")
                async with self._session_factory() as session:
                    user = await self._authentication.get_user_by_id(session, subject)
                if int(claims.get("auth_version", 0)) != user.auth_version:
                    raise PermissionError("Stream credential generation changed")
                if user.role.strip().lower() == "free user" or user.organization_plan.strip().lower() == "free":
                    raise PermissionError("Stream entitlement is unavailable")
                if not user.permissions or user.role.strip().lower() == "unassigned":
                    raise PermissionError("Stream permissions are unavailable")
                current = StreamPrincipal.from_user(user)
                if self._principal is not None and current != self._principal:
                    raise PermissionError("Stream principal changed")
                self._principal = current
                return current
        except (HTTPException, PermissionError, ValueError, TypeError) as exc:
            code = 1013 if isinstance(exc, HTTPException) and exc.status_code >= 500 else 4403
            await self._close_locked(code)
            raise StreamAuthorizationLost("Stream authorization ended") from None
        except Exception:
            await self._close_locked(1013)
            raise StreamAuthorizationLost("Stream authorization is unavailable") from None

    async def ensure_authorized(self) -> StreamPrincipal:
        async with self._lock:
            return await self._validate_locked()

    async def accept(self) -> None:
        async with self._lock:
            await self._validate_locked()
            try:
                async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                    await self._websocket.accept()
            except Exception:
                await self._close_locked(1013)
                raise StreamAuthorizationLost("Stream connection is unavailable") from None

    async def send_json(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            await self._validate_locked()
            try:
                async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                    await self._websocket.send_json(payload)
            except Exception:
                await self._close_locked(1013)
                raise StreamAuthorizationLost("Stream delivery is unavailable") from None
