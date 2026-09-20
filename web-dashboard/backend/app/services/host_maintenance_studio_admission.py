"""Request-only Production Studio maintenance admission.

The caller retains the shared authority lock through queue publication or retry.
No commits, policy seeding, artifact generation, worker claim or drain proof are
performed here. Execution ownership is a separate acceptance boundary.
"""
from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.host_maintenance_admission import (
    HostMaintenanceSnapshot,
    HostMaintenanceUnavailable,
    require_admission_open,
)

CONSUMER = "studio_job_requests"


async def require_studio_admission(session: AsyncSession) -> HostMaintenanceSnapshot:
    """Fence all queue producers in the existing caller transaction."""
    try:
        return await require_admission_open(session, required_scope=CONSUMER)
    except SQLAlchemyError:
        raise HostMaintenanceUnavailable(
            "Studio request admission is currently unavailable"
        ) from None
