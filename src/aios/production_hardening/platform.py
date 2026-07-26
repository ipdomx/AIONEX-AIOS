from __future__ import annotations

from dataclasses import dataclass

from .audit import AuditLog
from .config import ProductionConfigValidator
from .health import HealthRegistry
from .readiness import ProductionReadinessGate


@dataclass
class ProductionHardeningPlatform:
    audit: AuditLog
    config: ProductionConfigValidator
    health: HealthRegistry
    readiness: ProductionReadinessGate

    @classmethod
    def build_default(cls) -> "ProductionHardeningPlatform":
        config = ProductionConfigValidator()
        health = HealthRegistry()
        return cls(
            audit=AuditLog(),
            config=config,
            health=health,
            readiness=ProductionReadinessGate(config, health),
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "audit_log": self.audit is not None,
            "config_validator": self.config is not None,
            "health_registry": self.health is not None,
            "readiness_gate": self.readiness is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
