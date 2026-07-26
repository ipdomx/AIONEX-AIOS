from __future__ import annotations

from dataclasses import dataclass

from .auth import DashboardTokenService
from .contracts import DashboardContractRegistry
from .gateway import DashboardIntegrationGateway
from .health import DashboardIntegrationHealth
from .manifest import DashboardManifestValidator


@dataclass
class WebDashboardIntegrationPlatform:
    contracts: DashboardContractRegistry
    tokens: DashboardTokenService
    gateway: DashboardIntegrationGateway
    manifests: DashboardManifestValidator
    health: DashboardIntegrationHealth

    @classmethod
    def build_default(cls) -> "WebDashboardIntegrationPlatform":
        contracts = DashboardContractRegistry()
        tokens = DashboardTokenService()
        gateway = DashboardIntegrationGateway(contracts, tokens)
        return cls(
            contracts=contracts,
            tokens=tokens,
            gateway=gateway,
            manifests=DashboardManifestValidator(),
            health=DashboardIntegrationHealth(),
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "contract_registry": self.contracts is not None,
            "token_service": self.tokens is not None,
            "integration_gateway": self.gateway is not None,
            "manifest_validator": self.manifests is not None,
            "health_service": self.health is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
