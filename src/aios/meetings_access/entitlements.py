from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(slots=True)
class SessionEntitlement:
    entitlement_id: str
    owner_id: str
    user_id: str
    role: str
    included_minutes: int
    consumed_minutes: int = 0
    expires_at: datetime | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def remaining_minutes(self) -> int:
        return max(0, self.included_minutes - self.consumed_minutes)

    def is_active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        return self.expires_at is None or current < self.expires_at


class SessionEntitlementService:
    def __init__(self) -> None:
        self._entitlements: dict[str, SessionEntitlement] = {}

    def grant(self, entitlement: SessionEntitlement) -> SessionEntitlement:
        if entitlement.entitlement_id in self._entitlements:
            raise ValueError(f"duplicate entitlement: {entitlement.entitlement_id}")
        if entitlement.included_minutes < 0:
            raise ValueError("included minutes must be non-negative")
        self._entitlements[entitlement.entitlement_id] = entitlement
        return entitlement

    def consume(
        self,
        entitlement_id: str,
        *,
        owner_id: str,
        user_id: str,
        role: str,
        minutes: int,
    ) -> SessionEntitlement:
        if minutes <= 0:
            raise ValueError("minutes must be positive")
        entitlement = self._entitlements[entitlement_id]
        if entitlement.owner_id != owner_id or entitlement.user_id != user_id:
            raise PermissionError("entitlement does not belong to this owner and user")
        if entitlement.role != role:
            raise PermissionError("entitlement role does not match")
        if not entitlement.is_active():
            raise RuntimeError("entitlement has expired")
        if entitlement.remaining_minutes < minutes:
            raise RuntimeError("insufficient entitled minutes")
        entitlement.consumed_minutes += minutes
        return entitlement

    def list_active(self, owner_id: str, user_id: str) -> list[SessionEntitlement]:
        return [
            entitlement
            for entitlement in self._entitlements.values()
            if entitlement.owner_id == owner_id
            and entitlement.user_id == user_id
            and entitlement.is_active()
            and entitlement.remaining_minutes > 0
        ]
