"""Read retained Studio evidence before classifying cancellation or retry.

The caller holds a fresh, tenant-scoped StudioJob FOR UPDATE lock until its
existing transaction ends. Claim registration holds the same job lock before
creating evidence, so a concurrent claim cannot slip between this read and the
control mutation. Any retained row blocks a never-started classification, even
when its contents are malformed, old, orphaned or already settled. Absence of
history is NOT completion, filesystem-cleanup or host-drain proof.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    StudioCrashObservation, StudioExecution, StudioPoststartCancellation,
    StudioPrestartCancellation, StudioPublication, StudioSettlement,
)


class StudioControlEvidenceUnavailable(RuntimeError):
    """Missing or unreadable history must not authorize resetting a job."""


async def has_retained_studio_evidence(session: AsyncSession, job_id: str) -> bool:
    """Read all independent ledgers once, without autoflush, commit or side effects.

    No ownership/status/generation filter is allowed here: a surviving historical
    row must remain a fence after mutable business fields have been reset. Caller
    authentication and tenant lookup precede this function; no evidence content,
    filesystem paths or ownership nonces are returned.
    """
    try:
        if session.get_bind().dialect.name != "postgresql" or not session.in_transaction():
            raise StudioControlEvidenceUnavailable("Studio control evidence is unavailable")
        with session.no_autoflush:
            found = await session.scalar(select(or_(
                select(StudioExecution.id).where(StudioExecution.job_id == job_id).exists(),
                select(StudioPublication.id).where(StudioPublication.job_id == job_id).exists(),
                select(StudioSettlement.id).where(StudioSettlement.job_id == job_id).exists(),
                select(StudioPrestartCancellation.id).where(StudioPrestartCancellation.job_id == job_id).exists(),
                select(StudioPoststartCancellation.id).where(StudioPoststartCancellation.job_id == job_id).exists(),
                select(StudioCrashObservation.id).where(StudioCrashObservation.job_id == job_id).exists(),
            )))
        if type(found) is not bool:
            raise StudioControlEvidenceUnavailable("Studio control evidence is unavailable")
        return found
    except SQLAlchemyError:
        raise StudioControlEvidenceUnavailable("Studio control evidence is unavailable") from None
