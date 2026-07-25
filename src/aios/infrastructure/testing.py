from __future__ import annotations

from typing import Any

from .base import BaseInfrastructureIntegration
from .models import ConnectionProfile, ConnectionState, HealthReport, IntegrationDescriptor


class InMemoryIntegration(BaseInfrastructureIntegration):
    def __init__(self, descriptor: IntegrationDescriptor) -> None:
        super().__init__(descriptor)
        self.executions: list[tuple[str, dict[str, Any]]] = []
        self.context: dict[str, Any] = {}

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        self.context = context

    async def _disconnect(self) -> None:
        self.context = {}

    async def _health_check(self) -> HealthReport:
        state = self.state
        if state == ConnectionState.UNKNOWN:
            state = ConnectionState.DISCONNECTED
        return HealthReport(self.name, state, message="in-memory integration")

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        self.executions.append((capability, dict(payload)))
        return {"integration": self.name, "capability": capability, "payload": dict(payload)}
