from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DashboardModule(str, Enum):
    PROJECTS = "projects"
    TASKS = "tasks"
    GOVERNANCE = "governance"
    NOTIFICATIONS = "notifications"
    ANALYTICS = "analytics"
    MARKETPLACE = "marketplace"
    INFRASTRUCTURE = "infrastructure"
    SETTINGS = "settings"


@dataclass(frozen=True)
class DashboardContract:
    contract_id: str
    module: DashboardModule
    api_version: str
    route_prefix: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.contract_id.strip():
            raise ValueError("contract_id is required")
        if not self.api_version.strip():
            raise ValueError("api_version is required")
        if not self.route_prefix.startswith("/"):
            raise ValueError("route_prefix must start with /")


class DashboardContractRegistry:
    def __init__(self) -> None:
        self._contracts: dict[str, DashboardContract] = {}

    def register(self, contract: DashboardContract) -> DashboardContract:
        contract.validate()
        if contract.contract_id in self._contracts:
            raise ValueError(f"duplicate contract_id: {contract.contract_id}")
        self._contracts[contract.contract_id] = contract
        return contract

    def get(self, contract_id: str) -> DashboardContract:
        try:
            return self._contracts[contract_id]
        except KeyError as exc:
            raise LookupError(f"dashboard contract not found: {contract_id}") from exc

    def list(self) -> list[DashboardContract]:
        return list(self._contracts.values())
