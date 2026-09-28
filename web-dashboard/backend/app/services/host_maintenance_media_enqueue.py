"""Transactional downstream media queue-publication admission.

The existing Studio authority is a conservative supplemental fence, not a new
schema declaration or proof of complete host quiescence. The caller must keep
this same transaction through publication and commit/rollback. No provider I/O,
retry, settlement, policy initialization or authority transition happens here.
Already-started work and cleanup after rollback need separate ownership proofs.
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.host_maintenance_admission import (
    HostMaintenanceClosed,
    HostMaintenanceSnapshot,
    HostMaintenanceUnavailable,
)
from app.services.host_maintenance_studio_admission import require_studio_admission

MEDIA_ENQUEUE_CONSUMERS = frozenset({
    "design_image", "audio_speech", "audio_transcript", "audio_dubbing",
    "audio_music", "audio_song", "video", "identity_media", "media_graph", "three_d",
})


async def require_media_enqueue_admission(
    session: AsyncSession, *, consumer: str
) -> HostMaintenanceSnapshot:
    """Fence publication before queue reads or autoflush in the caller session.

    Return 503 for closed/unavailable maintenance without exposing operation
    identifiers. Programming errors still propagate and cannot become success.
    """
    if consumer not in MEDIA_ENQUEUE_CONSUMERS:
        raise ValueError("Unknown downstream media enqueue consumer")
    try:
        return await require_studio_admission(session)
    except HostMaintenanceClosed:
        raise HTTPException(status_code=503, detail={
            "code": "MEDIA_MAINTENANCE_CLOSED",
            "message": "Media queue publication is paused for maintenance",
        }) from None
    except HostMaintenanceUnavailable:
        raise HTTPException(status_code=503, detail={
            "code": "MEDIA_MAINTENANCE_UNAVAILABLE",
            "message": "Media queue admission is temporarily unavailable",
        }) from None
