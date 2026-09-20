"""Request/resume-only Realtime media maintenance admission.

New room provisioning, join-token issuance, recording requests and provider
recording starts are fenced. Cleanup/control operations (leave, close, stop)
remain available while admission is closed. The caller retains the shared lock
through its existing transaction; this helper never commits or repairs authority.
"""
from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.host_maintenance_admission import (
    HostMaintenanceSnapshot,
    HostMaintenanceUnavailable,
    require_admission_open,
)

CONSUMER = "realtime_media_requests"


async def require_realtime_admission(session: AsyncSession) -> HostMaintenanceSnapshot:
    """Fence new/resumed Realtime provider work in the caller transaction."""
    try:
        return await require_admission_open(session, required_scope=CONSUMER)
    except SQLAlchemyError:
        raise HostMaintenanceUnavailable(
            "Realtime media admission is currently unavailable"
        ) from None
