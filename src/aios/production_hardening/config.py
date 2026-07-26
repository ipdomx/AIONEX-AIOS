from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DeploymentEnvironment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


@dataclass(frozen=True)
class EnvironmentConfig:
    environment: DeploymentEnvironment
    debug: bool = False
    secret_provider: str | None = None
    database_url: str | None = None
    allowed_hosts: tuple[str, ...] = ()
    tls_required: bool = True
    metadata: dict[str, str] = field(default_factory=dict)


class ProductionConfigValidator:
    def validate(self, config: EnvironmentConfig) -> dict[str, bool]:
        checks = {
            "debug_disabled": not config.debug,
            "secret_provider": bool(config.secret_provider and config.secret_provider.strip()),
            "database_url": bool(config.database_url and config.database_url.strip()),
            "allowed_hosts": bool(config.allowed_hosts),
            "tls_required": config.tls_required,
        }
        if config.environment is not DeploymentEnvironment.PRODUCTION:
            checks["ready"] = True
            return checks
        checks["ready"] = all(checks.values())
        return checks

    def assert_ready(self, config: EnvironmentConfig) -> None:
        result = self.validate(config)
        if not result["ready"]:
            failed = sorted(name for name, passed in result.items() if name != "ready" and not passed)
            raise ValueError(f"production configuration is not ready: {', '.join(failed)}")
