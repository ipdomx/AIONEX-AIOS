"""Supplemental lifetime admission for ordinary operations-observer work.

The schema8 authority is not widened. Independent safety reconciliation must
run before this fence; auto-disarm and manual-review writes are never frozen by
it. This is not a provider-drain, crash-settlement or full-host certificate.
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

# A separate lock-only connection cannot be released by the observer's inner
# business commits or exhaust its business pool. No idle connection is retained.
_fence_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool,
                                    pool_pre_ping=True, echo=False)
SessionLocal = async_sessionmaker(_fence_engine, expire_on_commit=False)


async def _open(session: AsyncSession) -> bool:
    try:
        snapshot = await read_admission_snapshot(session)
    except (HostMaintenanceUnavailable, SQLAlchemyError, OSError):
        return False
    return snapshot.schema_version == REALTIME_REQUEST_SCHEMA_VERSION and snapshot.is_open


async def run_observer_observation(action: Callable[[], Awaitable[None]]) -> bool:
    """Retain one admission lock through probes, commits and alert publication.

    Denial never constructs an action coroutine. Cancellation while acquiring the
    lock cancels the waiter. After admission, outer cancellation waits for the
    one existing action, including an already-running storage/network callback;
    it does not detach or replay that action. Independent child cancellation,
    process death or lost lock connectivity still requires reconciliation.
    """
    admitted = False

    async def guarded() -> bool:
        nonlocal admitted
        async with SessionLocal() as session:
            if not await _open(session):
                return False
            admitted = True
            await action()
            return True

    task = asyncio.create_task(guarded(), name="aionex-maintenance-bound-observer")
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


async def close_observer_admission() -> None:
    """Dispose the supplemental engine after the observer's last action ends."""
    await _fence_engine.dispose()
