from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EntitlementState(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass
class Entitlement:
    entitlement_id: str
    license_id: str
    principal_id: str
    capabilities: set[str] = field(default_factory=set)
    state: EntitlementState = EntitlementState.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class EntitlementManager:
    def __init__(self) -> None:
        self._entitlements: dict[str, Entitlement] = {}

    def grant(self, entitlement: Entitlement) -> Entitlement:
        if not entitlement.entitlement_id.strip() or not entitlement.license_id.strip() or not entitlement.principal_id.strip():
            raise ValueError("entitlement_id, license_id, and principal_id are required")
        if entitlement.entitlement_id in self._entitlements:
            raise ValueError(f"duplicate entitlement_id: {entitlement.entitlement_id}")
        self._entitlements[entitlement.entitlement_id] = entitlement
        return entitlement

    def get(self, entitlement_id: str) -> Entitlement:
        try:
            return self._entitlements[entitlement_id]
        except KeyError as exc:
            raise LookupError(f"entitlement not found: {entitlement_id}") from exc

    def authorize(self, principal_id: str, capability: str) -> bool:
        return any(
            item.principal_id == principal_id
            and item.state is EntitlementState.ACTIVE
            and capability in item.capabilities
            for item in self._entitlements.values()
        )

    def revoke(self, entitlement_id: str) -> None:
        self.get(entitlement_id).state = EntitlementState.REVOKED

    def list_for_principal(self, principal_id: str) -> list[Entitlement]:
        return [item for item in self._entitlements.values() if item.principal_id == principal_id]
