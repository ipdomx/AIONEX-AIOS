from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class IntegrationHealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class IntegrationHealthReport:
    status: IntegrationHealthStatus
    checks: dict[str, bool]
    details: dict[str, str] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DashboardIntegrationHealth:
    def evaluate(self, checks: dict[str, bool], details: dict[str, str] | None = None) -> IntegrationHealthReport:
        values = list(checks.values())
        if values and all(values):
            status = IntegrationHealthStatus.HEALTHY
        elif any(values):
            status = IntegrationHealthStatus.DEGRADED
        else:
            status = IntegrationHealthStatus.UNAVAILABLE
        return IntegrationHealthReport(status=status, checks=dict(checks), details=dict(details or {}))
