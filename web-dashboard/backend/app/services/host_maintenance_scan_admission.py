"""Request-only Security Lab maintenance admission.

This is producer coverage, NOT worker/scanner ownership or a drain proof. All
callers retain the shared authority lock through their existing transaction.
No helper commits, seeds policy/authority, resolves DNS, starts tools, or retries.
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.host_maintenance_admission import (
    HostMaintenanceSnapshot,
    HostMaintenanceUnavailable,
    require_admission_open,
)

CONSUMER = "security_scan_requests"


async def require_scan_admission(session: AsyncSession) -> HostMaintenanceSnapshot:
    """Fence a producer before policy/DNS or business locks; use the caller TX."""
    try:
        return await require_admission_open(session, required_scope=CONSUMER)
    except SQLAlchemyError:
        # Never return driver/connection details through an HTTP error response.
        raise HostMaintenanceUnavailable(
            "Security scan admission is currently unavailable"
        ) from None
