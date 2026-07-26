from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import DashboardContract


@dataclass(frozen=True)
class DashboardManifest:
    dashboard_id: str
    name: str
    version: str
    entrypoint: str
    contracts: tuple[str, ...]
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    metadata: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.dashboard_id.strip() or not self.name.strip():
            raise ValueError("dashboard_id and name are required")
        if not self.version.strip():
            raise ValueError("dashboard version is required")
        if not self.entrypoint.strip():
            raise ValueError("dashboard entrypoint is required")
        if not self.contracts:
            raise ValueError("dashboard requires at least one contract")


class DashboardManifestValidator:
    def validate(
        self,
        manifest: DashboardManifest,
        available_contracts: list[DashboardContract],
    ) -> dict[str, object]:
        manifest.validate()
        indexed = {contract.contract_id: contract for contract in available_contracts}
        missing = [contract_id for contract_id in manifest.contracts if contract_id not in indexed]
        available_capabilities = {
            capability
            for contract_id in manifest.contracts
            if contract_id in indexed
            for capability in indexed[contract_id].capabilities
        }
        missing_capabilities = sorted(manifest.required_capabilities - available_capabilities)
        return {
            "valid": not missing and not missing_capabilities,
            "missing_contracts": missing,
            "missing_capabilities": missing_capabilities,
        }
