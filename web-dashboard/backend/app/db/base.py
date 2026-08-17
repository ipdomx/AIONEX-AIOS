"""Database engine, sessions, and declarative base."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings


class Base(DeclarativeBase):
    pass


_engine_options: dict[str, Any] = {
    "pool_pre_ping": True,
    "echo": settings.DATABASE_ECHO,
}
if settings.DATABASE_POOLING_ENABLED:
    _engine_options.update(
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT_SECONDS,
    )
else:
    # Workers and the test suite keep NullPool so connections never cross async
    # event-loop/process boundaries. Production API containers opt into pooling.
    _engine_options["poolclass"] = NullPool

engine = create_async_engine(settings.DATABASE_URL, **_engine_options)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
