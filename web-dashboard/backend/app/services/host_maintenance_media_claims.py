"""Supplemental downstream media claim/reaper fence, not a drain certificate.

These consumers conservatively honor the existing Studio-request maintenance
lock. This does not rewrite its versioned scope declaration, certify deployment,
or assert that work admitted before closure has stopped. Admission of producers,
provider submission/publication and external-resource reconciliation remain
separate boundaries. The host cutover must still reject incomplete evidence.

Keep this shared lock in the SAME transaction as the queue claim or lease reaper.
A closed/unavailable gate returns no work, without repairing state or advancing
leases. A successful check never commits, so closure cannot overtake that claim.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.host_maintenance_admission import (
    HostMaintenanceClosed,
    HostMaintenanceUnavailable,
)
from app.services.host_maintenance_studio_admission import require_studio_admission

MEDIA_CLAIM_CONSUMERS = frozenset({
    "design_image", "audio_speech", "audio_transcript", "audio_dubbing",
    "audio_music", "audio_song", "video", "identity_media", "three_d",
    "media_render", "design_image_derivative",
})


async def media_claim_admission_open(
    session: AsyncSession, *, consumer: str
) -> bool:
    """Take the existing shared authority lock before any queue mutation/read."""
    if consumer not in MEDIA_CLAIM_CONSUMERS:
        raise ValueError("Unknown downstream media claim consumer")
    try:
        await require_studio_admission(session)
    except (HostMaintenanceClosed, HostMaintenanceUnavailable):
        return False
    return True
