from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import EnvironmentConfig, ProductionConfigValidator
from .health import HealthRegistry, HealthStatus


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    checks: dict[str, bool]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ProductionReadinessGate:
    def __init__(self, config_validator: ProductionConfigValidator, health: HealthRegistry) -> None:
        self.config_validator = config_validator
        self.health = health

    def evaluate(self, config: EnvironmentConfig, required_components: tuple[str, ...] = ()) -> ReadinessReport:
        config_checks = self.config_validator.validate(config)
        checks: dict[str, bool] = {
            f"config.{name}": value for name, value in config_checks.items() if name != "ready"
        }
        checks["config.ready"] = config_checks["ready"]
        for component in required_components:
            try:
                checks[f"health.{component}"] = self.health.get(component).status is HealthStatus.HEALTHY
            except LookupError:
                checks[f"health.{component}"] = False
        checks["health.overall"] = self.health.overall() is HealthStatus.HEALTHY
        return ReadinessReport(ready=all(checks.values()), checks=checks)

    def assert_ready(self, config: EnvironmentConfig, required_components: tuple[str, ...] = ()) -> None:
        report = self.evaluate(config, required_components)
        if not report.ready:
            failed = sorted(name for name, passed in report.checks.items() if not passed)
            raise RuntimeError(f"production readiness gate failed: {', '.join(failed)}")
