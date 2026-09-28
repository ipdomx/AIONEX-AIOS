"""Admission for work performed outside downstream media claim methods.

Use the same existing Studio maintenance authority and caller transaction as
D10A. This supplements three worker cycles only; it is not a declaration of
full-host coverage or proof that a crashed process/provider has drained.
"""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.host_maintenance_media_claims import media_claim_admission_open

MEDIA_CYCLE_CONSUMERS = frozenset({"audio_song", "audio_dubbing", "three_d"})
SONG_BALANCE_TIMEOUT_SECONDS = 20.0


async def media_cycle_admission_open(session: AsyncSession, *, consumer: str) -> bool:
    """Hold shared maintenance admission until the protected transaction ends."""
    if consumer not in MEDIA_CYCLE_CONSUMERS:
        raise ValueError("Unknown downstream media cycle consumer")
    return await media_claim_admission_open(session, consumer=consumer)


async def finish_started_cleanup(work: Coroutine[Any, Any, dict[str, int]]) -> dict[str, int]:
    """Defer caller cancellation until the already-started cleanup has settled.

    Cancelling an await of to_thread does not stop its filesystem operation.
    Keep the caller's database session/maintenance lock alive while this child
    finishes. Repeated cancellation never starts a second cleanup or drops the
    lock early. Process death or independent child cancellation still requires
    operational reconciliation; this is not a crash-drain certificate.
    """
    task = asyncio.create_task(work, name="aionex-maintenance-bound-cleanup")
    cancellation_requested = False
    while True:
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancellation_requested = True
            continue
        except Exception:
            if cancellation_requested:
                raise asyncio.CancelledError from None
            raise
        if cancellation_requested:
            raise asyncio.CancelledError
        return result
