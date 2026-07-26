from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class LicensePlan(str, Enum):
    FREE = "free"
    TRIAL = "trial"
    SUBSCRIPTION = "subscription"
    PERPETUAL = "perpetual"
    ENTERPRISE = "enterprise"


class LicenseState(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


@dataclass
class License:
    license_id: str
    item_id: str
    organization_id: str
    plan: LicensePlan
    state: LicenseState = LicenseState.ACTIVE
    seats: int = 1
    expires_at: datetime | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_active(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        if self.state is not LicenseState.ACTIVE:
            return False
        if self.expires_at is not None and current >= self.expires_at:
            self.state = LicenseState.EXPIRED
            return False
        return True


class LicenseManager:
    def __init__(self) -> None:
        self._licenses: dict[str, License] = {}

    def issue(self, license: License) -> License:
        if not license.license_id.strip() or not license.item_id.strip() or not license.organization_id.strip():
            raise ValueError("license_id, item_id, and organization_id are required")
        if license.seats <= 0:
            raise ValueError("seats must be positive")
        if license.license_id in self._licenses:
            raise ValueError(f"duplicate license_id: {license.license_id}")
        self._licenses[license.license_id] = license
        return license

    def get(self, license_id: str) -> License:
        try:
            return self._licenses[license_id]
        except KeyError as exc:
            raise LookupError(f"license not found: {license_id}") from exc

    def revoke(self, license_id: str) -> None:
        self.get(license_id).state = LicenseState.REVOKED

    def list_for_organization(self, organization_id: str, active_only: bool = False) -> list[License]:
        items = [item for item in self._licenses.values() if item.organization_id == organization_id]
        if active_only:
            items = [item for item in items if item.is_active()]
        return items
