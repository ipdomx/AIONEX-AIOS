from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .catalog import MarketplaceCatalog, PublicationState
from .entitlements import EntitlementManager
from .licensing import LicenseManager


class InstallationState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    FAILED = "failed"
    SUSPENDED = "suspended"
    REMOVED = "removed"


@dataclass
class Installation:
    installation_id: str
    item_id: str
    organization_id: str
    license_id: str
    requested_by: str
    state: InstallationState = InstallationState.PENDING
    configuration: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition(self, state: InstallationState) -> None:
        allowed = {
            InstallationState.PENDING: {InstallationState.ACTIVE, InstallationState.FAILED, InstallationState.REMOVED},
            InstallationState.ACTIVE: {InstallationState.SUSPENDED, InstallationState.REMOVED, InstallationState.FAILED},
            InstallationState.FAILED: {InstallationState.PENDING, InstallationState.REMOVED},
            InstallationState.SUSPENDED: {InstallationState.ACTIVE, InstallationState.REMOVED},
            InstallationState.REMOVED: set(),
        }
        if state not in allowed[self.state]:
            raise ValueError(f"invalid installation transition: {self.state.value} -> {state.value}")
        self.state = state
        self.updated_at = datetime.now(timezone.utc)


class InstallationManager:
    def __init__(self, catalog: MarketplaceCatalog, licenses: LicenseManager, entitlements: EntitlementManager) -> None:
        self.catalog = catalog
        self.licenses = licenses
        self.entitlements = entitlements
        self._installations: dict[str, Installation] = {}

    def install(self, installation: Installation) -> Installation:
        if not installation.installation_id.strip() or not installation.requested_by.strip():
            raise ValueError("installation_id and requested_by are required")
        if installation.installation_id in self._installations:
            raise ValueError(f"duplicate installation_id: {installation.installation_id}")
        item = self.catalog.get(installation.item_id)
        if item.state is not PublicationState.PUBLISHED:
            raise ValueError("marketplace item is not published")
        license = self.licenses.get(installation.license_id)
        if license.item_id != installation.item_id or license.organization_id != installation.organization_id:
            raise ValueError("license does not match installation")
        if not license.is_active():
            raise PermissionError("license is not active")
        if not self.entitlements.authorize(installation.requested_by, f"marketplace.install:{installation.item_id}"):
            raise PermissionError("principal is not entitled to install this item")
        installation.transition(InstallationState.ACTIVE)
        self._installations[installation.installation_id] = installation
        return installation

    def get(self, installation_id: str) -> Installation:
        try:
            return self._installations[installation_id]
        except KeyError as exc:
            raise LookupError(f"installation not found: {installation_id}") from exc

    def remove(self, installation_id: str) -> None:
        self.get(installation_id).transition(InstallationState.REMOVED)

    def list_for_organization(self, organization_id: str) -> list[Installation]:
        return [item for item in self._installations.values() if item.organization_id == organization_id]
