from __future__ import annotations

import asyncio
from time import perf_counter

from .models import ConnectionState, HealthReport
from .registry import IntegrationRegistry


class InfrastructureHealthMonitor:
    def __init__(self, registry: IntegrationRegistry) -> None:
        self._registry = registry
        self._reports: dict[str, HealthReport] = {}

    async def check(self, name: str) -> HealthReport:
        integration = self._registry.get(name)
        started = perf_counter()
        try:
            report = await integration.health_check()
        except Exception as exc:
            report = HealthReport(name, ConnectionState.FAILED, message=str(exc))
        if report.latency_ms is None:
            report = HealthReport(report.integration, report.state,
                                  latency_ms=(perf_counter() - started) * 1000,
                                  message=report.message, details=report.details)
        self._reports[name] = report
        return report

    async def check_all(self) -> tuple[HealthReport, ...]:
        names = [item.name for item in self._registry.all()]
        return tuple(await asyncio.gather(*(self.check(name) for name in names)))

    def snapshot(self) -> dict[str, dict]:
        return {
            name: {
                "state": report.state.value,
                "latency_ms": report.latency_ms,
                "message": report.message,
                "details": dict(report.details),
            }
            for name, report in sorted(self._reports.items())
        }
