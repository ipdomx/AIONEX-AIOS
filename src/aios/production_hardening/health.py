from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class ComponentHealth:
    component: str
    status: HealthStatus
    message: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, object] = field(default_factory=dict)


class HealthRegistry:
    def __init__(self) -> None:
        self._components: dict[str, ComponentHealth] = {}

    def report(self, health: ComponentHealth) -> ComponentHealth:
        if not health.component.strip():
            raise ValueError("component is required")
        self._components[health.component] = health
        return health

    def get(self, component: str) -> ComponentHealth:
        try:
            return self._components[component]
        except KeyError as exc:
            raise LookupError(f"component health not found: {component}") from exc

    def snapshot(self) -> dict[str, str]:
        return {name: health.status.value for name, health in sorted(self._components.items())}

    def overall(self) -> HealthStatus:
        statuses = {health.status for health in self._components.values()}
        if not statuses:
            return HealthStatus.UNHEALTHY
        if HealthStatus.UNHEALTHY in statuses:
            return HealthStatus.UNHEALTHY
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY
