"""FR09: release successful authenticated READ transactions without skipping checks."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, auth_service, current_user


def _request(method: str) -> Request:
    return Request({
        "type": "http",
        "method": method,
        "scheme": "https",
        "path": "/api/v1/projects",
        "headers": [(b"host", b"backend")],
    })


def _actor() -> UserRecord:
    return UserRecord(
        id="fr09-test-user",
        email="fr09@example.invalid",
        name="Load Test",
        password_hash="unused",
        role="Member",
        organization_id="fr09-test-org",
        organization_name="Isolated Test",
        organization_plan="free",
        permissions=["projects:read"],
        auth_version=3,
    )


def _stub_auth(monkeypatch: pytest.MonkeyPatch):
    decoder = AsyncMock(return_value={"sub": "fr09-test-user", "auth_version": 3})
    reader = AsyncMock(return_value=_actor())
    monkeypatch.setattr(auth_service, "decode_access_token", decoder)
    monkeypatch.setattr(auth_service, "get_user_by_id", reader)
    return decoder, reader


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_authenticated_reads_release_the_database_transaction(
    method: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    decoder, reader = _stub_auth(monkeypatch)

    async def scenario() -> None:
        async with AsyncSession(expire_on_commit=False) as session:
            await session.begin()
            assert session.in_transaction()
            actor = await current_user(
                request=_request(method), token="synthetic-test-token", session=session,
            )
            assert actor.id == "fr09-test-user"
            assert actor.organization_id == "fr09-test-org"
            assert actor.permissions == ["projects:read"]
            assert not session.in_transaction()
            # Downstream handlers can reuse the same session in a new transaction.
            await session.begin()
            assert session.in_transaction()

    asyncio.run(scenario())
    decoder.assert_awaited_once_with("synthetic-test-token")
    reader.assert_awaited_once()


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
def test_mutations_keep_original_transaction_boundary(
    method: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_auth(monkeypatch)

    async def scenario() -> None:
        async with AsyncSession() as session:
            await session.begin()
            actor = await current_user(
                request=_request(method), token="synthetic-test-token", session=session,
            )
            assert actor.id == "fr09-test-user"
            assert session.in_transaction()

    asyncio.run(scenario())


def test_stale_auth_generation_remains_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, reader = _stub_auth(monkeypatch)
    reader.return_value = _actor()
    monkeypatch.setattr(
        auth_service, "decode_access_token",
        AsyncMock(return_value={"sub": "fr09-test-user", "auth_version": 2}),
    )

    async def scenario() -> None:
        async with AsyncSession() as session:
            await session.begin()
            with pytest.raises(HTTPException) as denied:
                await current_user(
                    request=_request("GET"), token="stale-test-token", session=session,
                )
            assert denied.value.status_code == 401
            assert session.in_transaction()

    asyncio.run(scenario())


def test_revoked_token_rejected_before_database_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_service, "decode_access_token",
        AsyncMock(side_effect=HTTPException(status_code=401, detail="revoked")),
    )
    reader = AsyncMock()
    monkeypatch.setattr(auth_service, "get_user_by_id", reader)

    async def scenario() -> None:
        async with AsyncSession() as session:
            with pytest.raises(HTTPException) as denied:
                await current_user(
                    request=_request("GET"), token="revoked-test-token", session=session,
                )
            assert denied.value.status_code == 401

    asyncio.run(scenario())
    reader.assert_not_awaited()
