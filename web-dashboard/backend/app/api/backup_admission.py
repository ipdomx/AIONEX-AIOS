"""HTTP boundary for backup enqueue admission in the caller's transaction."""

from fastapi import HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.host_maintenance_admission import (
    HostMaintenanceClosed,
    HostMaintenanceUnavailable,
    require_admission_open,
)

BACKUP_ADMISSION_CLOSED_DETAIL = (
    "Backup and restore admission is temporarily closed for maintenance."
)
BACKUP_ADMISSION_UNAVAILABLE_DETAIL = (
    "Backup and restore admission is currently unavailable."
)


async def require_backup_enqueue_admission(session: AsyncSession) -> None:
    """Retain shared admission through the existing enqueue commit or rollback."""
    try:
        await require_admission_open(session, required_scope="backup_cycles")
    except HostMaintenanceClosed:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BACKUP_ADMISSION_CLOSED_DETAIL,
        ) from None
    except (HostMaintenanceUnavailable, SQLAlchemyError):
        # Database diagnostics can contain URLs or parameters. The API and its
        # existing Owner audit receive only this constant availability message.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=BACKUP_ADMISSION_UNAVAILABLE_DETAIL,
        ) from None
