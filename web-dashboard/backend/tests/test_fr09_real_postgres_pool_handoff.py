"""FR09: enforce real-PostgreSQL auth pool release before a long GET response.

This is a tiny, deterministic single-connection integration regression, not a
5,000-user capacity test. No customer tables, paid providers or writes are used.
"""

from __future__ import annotations

import asyncio
import os
from unittest import SkipTest
from unittest.mock import AsyncMock, patch

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.auth import UserRecord, auth_service, current_user


def _get_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/api/v1/projects",
            "headers": [(b"host", b"backend")],
        }
    )


def _actor() -> UserRecord:
    return UserRecord(
        id="fr09-pool-regression",
        email="fr09-pool@example.invalid",
        name="Synthetic test user",
        password_hash="unused",
        role="Member",
        organization_id="fr09-pool-test-org",
        organization_name="Synthetic Test",
        organization_plan="free",
        permissions=["projects:read"],
        auth_version=17,
    )


def test_real_postgres_connection_released_before_get_response_finishes() -> None:
    """Second GET must authenticate while first response is still blocked.

    Before PR1008, the first GET pinned the sole SQLAlchemy connection until
    its response completed and the second GET hit the pool timeout. This tests
    the *actual* asyncpg connection pool, while stubbing just identity lookup
    and token validation so no application customer data is needed.
    """
    if os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}:
        raise SkipTest("Never run FR09 integration regression in production")
    database_url = os.getenv("DATABASE_URL", "").strip()
    try:
        url = make_url(database_url)
    except (TypeError, ValueError, ArgumentError):
        raise SkipTest("Requires a disposable PostgreSQL test database")
    database_name = (url.database or "").lower()
    if (
        url.drivername != "postgresql+asyncpg"
        or not any(tag in database_name for tag in ("test", "ci", "disposable"))
    ):
        raise SkipTest("Requires explicit disposable PostgreSQL test database")

    async def read_actor(session: AsyncSession, user_id: str) -> UserRecord:
        assert user_id == "fr09-pool-regression"
        assert (await session.scalar(text("SELECT 1"))) == 1
        return _actor()

    async def scenario() -> None:
        engine = create_async_engine(
            database_url,
            pool_size=1,
            max_overflow=0,
            pool_timeout=1.5,
            pool_pre_ping=False,
        )
        first_authenticated = asyncio.Event()
        finish_first_response = asyncio.Event()

        async def first_get() -> None:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                actor = await current_user(
                    _get_request(), token="synthetic-1", session=session
                )
                assert actor.id == "fr09-pool-regression"
                # Do not assert internal state here: test the real pool instead.
                first_authenticated.set()
                # Long response boundary: first session intentionally stays alive.
                await asyncio.wait_for(finish_first_response.wait(), timeout=5.0)

        async def second_get() -> None:
            await asyncio.wait_for(first_authenticated.wait(), timeout=5.0)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                actor = await asyncio.wait_for(
                    current_user(_get_request(), token="synthetic-2", session=session),
                    timeout=3.0,
                )
                assert actor.id == "fr09-pool-regression"
                assert not session.in_transaction()
                finish_first_response.set()

        try:
            await asyncio.wait_for(
                asyncio.gather(first_get(), second_get()), timeout=7.0
            )
        finally:
            finish_first_response.set()
            await engine.dispose()

    # Keep compatibility with the project's Python 3.8 Ruff parser.
    with patch.object(
        auth_service,
        "decode_access_token",
        AsyncMock(
            return_value={"sub": "fr09-pool-regression", "auth_version": 17}
        ),
    ):
        with patch.object(auth_service, "get_user_by_id", read_actor):
            asyncio.run(scenario())


if __name__ == "__main__":
    test_real_postgres_connection_released_before_get_response_finishes()
    print("FR09_REAL_POSTGRES_AUTH_POOL_HANDOFF_PASS")
