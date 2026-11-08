"""T-20: idle realtime sockets re-check the credential cheaply and fully on a cadence."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.realtime import authorized_socket as sock


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed_with: int | None = None

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


class FakeAuth:
    def __init__(self, claims: dict | Exception) -> None:
        self.claims = claims

    async def decode_access_token(self, _token: str) -> dict:
        if isinstance(self.claims, Exception):
            raise self.claims
        return dict(self.claims)


def _socket(claims: dict | Exception) -> tuple[sock.AuthorizedRealtimeSocket, FakeWebSocket]:
    ws = FakeWebSocket()

    def no_db():
        raise AssertionError("the cheap idle check must not open a database session")

    guarded = sock.AuthorizedRealtimeSocket(ws, "token", no_db, authentication=FakeAuth(claims))
    guarded._principal = sock.StreamPrincipal("u1", "o1", 3, "Owner", "business", ("projects:read",))
    return guarded, ws


@pytest.mark.asyncio
async def test_current_token_keeps_socket_without_database() -> None:
    guarded, ws = _socket({"sub": "u1", "auth_version": 3})
    assert (await guarded.ensure_token_current()).user_id == "u1"
    assert ws.closed_with is None


@pytest.mark.asyncio
@pytest.mark.parametrize("claims", [
    HTTPException(status_code=401, detail="Token has been revoked"),
    {"sub": "u1", "auth_version": 4},
    {"sub": "someone-else", "auth_version": 3},
])
async def test_revoked_or_changed_token_closes_idle_socket(claims) -> None:
    guarded, ws = _socket(claims)
    with pytest.raises(sock.StreamAuthorizationLost):
        await guarded.ensure_token_current()
    assert ws.closed_with == 4403 and guarded.closed


def test_full_revalidation_cadence_is_bounded() -> None:
    # Account/role/permission changes are enforced before every delivered event; idle
    # sockets still get a full database check at least every 30 seconds.
    assert sock.IDLE_REVALIDATION_SECONDS * sock.FULL_REVALIDATION_EVERY_IDLE_TICKS <= 30
