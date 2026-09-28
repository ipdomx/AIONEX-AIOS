"""Supplemental admission for the Owner/user Telegram worker action loops.

The existing schema8 authority is read without adding a scope or changing its
version. This does not certify deployment, Telegram delivery, crash drainage or
full-host coverage. Poll admission is a short observation, not a long-poll lock;
action admission is checked again after polling and held through offset commit.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.services.host_maintenance_admission import (
    REALTIME_REQUEST_SCHEMA_VERSION,
    HostMaintenanceUnavailable,
    read_admission_snapshot,
)

CONSUMERS = frozenset({"owner", "user"})
# Never occupy the business pool while an admitted handler awaits another
# session. Each worker processes one batch at a time; no idle connections remain.
_fence_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool,
                                    pool_pre_ping=True, echo=False)
SessionLocal = async_sessionmaker(_fence_engine, expire_on_commit=False)


def _consumer(value: str) -> None:
    if value not in CONSUMERS:
        raise ValueError("Unknown Telegram maintenance consumer")


async def _open(session: AsyncSession) -> bool:
    try:
        snapshot = await read_admission_snapshot(session)
    except (HostMaintenanceUnavailable, SQLAlchemyError, OSError):
        return False
    return snapshot.schema_version == REALTIME_REQUEST_SCHEMA_VERSION and snapshot.is_open


async def telegram_poll_admission_open(*, consumer: str) -> bool:
    """Do not initiate another poll when maintenance already denies admission.

    A poll already in flight may finish after closure. Its result must separately
    pass run_telegram_action before any handler, reply, audit or offset write.
    """
    _consumer(consumer)
    async with SessionLocal() as session:
        return await _open(session)


async def wait_for_telegram_admission(stop: asyncio.Event) -> None:
    """Keep closed workers responsive to shutdown without a hot polling loop."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=1.0)
    except TimeoutError:
        return


async def run_telegram_action(action: Callable[[], Awaitable[None]], *, consumer: str) -> bool:
    """Call one admitted action exactly once while retaining a separate lock.

    No action coroutine is constructed or executed on denial. Inner business transactions
    cannot release the lock. After admission, defer outer cancellation until the
    existing handler and its offset/audit work return; never detach or replay it.
    Process death, independent inner cancellation, lost connections, and unknown
    remote outcomes remain operational reconciliation, not settled delivery.
    """
    _consumer(consumer)
    admitted = False

    async def guarded() -> bool:
        nonlocal admitted
        async with SessionLocal() as session:
            if not await _open(session):
                return False
            admitted = True
            await action()
            return True

    task = asyncio.create_task(guarded(), name="aionex-maintenance-bound-telegram")
    cancelled = False
    acquisition_cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
            if not admitted and not task.done() and not acquisition_cancelled:
                acquisition_cancelled = True
                task.cancel()
            if task.done():
                try:
                    task.result()
                except Exception:
                    raise asyncio.CancelledError from None
                raise
            continue
        except Exception:
            if cancelled:
                raise asyncio.CancelledError from None
            raise
        if cancelled:
            raise asyncio.CancelledError
        return result


async def close_telegram_admission() -> None:
    """Dispose the separate engine once the worker and its action have ended."""
    await _fence_engine.dispose()
