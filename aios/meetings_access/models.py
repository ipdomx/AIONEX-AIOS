from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SessionRole(str, Enum):
    EMPLOYEE = "employee"
    ENGINEER = "engineer"
    MANAGER = "manager"
    CHIEF_ENGINEER = "chief_engineer"


class SessionStatus(str, Enum):
    REQUESTED = "requested"
    PENDING_OWNER_APPROVAL = "pending_owner_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class RoleSessionRequest:
    session_id: str
    user_id: str
    project_id: str
    role: SessionRole
    requested_minutes: int
    paid: bool
    reason: str
    status: SessionStatus = SessionStatus.REQUESTED
    owner_id: str | None = None
    approved_minutes: int | None = None
    price_minor: int = 0
    currency: str = "EUR"
    starts_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if self.requested_minutes <= 0:
            raise ValueError("requested_minutes must be positive")
        if self.price_minor < 0:
            raise ValueError("price_minor cannot be negative")
        if not self.currency:
            raise ValueError("currency is required")
