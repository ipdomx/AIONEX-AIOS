from __future__ import annotations

from typing import Any

from .base import BaseInfrastructureIntegration
from .models import (ConnectionProfile, ConnectionState, HealthReport,
                     IntegrationCapability, IntegrationDescriptor, IntegrationKind)


class KubernetesProvider(BaseInfrastructureIntegration):
    _capabilities = (
        "clusters", "namespaces", "nodes", "pods", "deployments", "services", "config_maps",
        "secrets", "apply", "delete", "scale", "rollout", "logs", "exec", "events", "health",
    )

    def __init__(self, name: str = "kubernetes") -> None:
        descriptor = IntegrationDescriptor(
            name=name,
            kind=IntegrationKind.ORCHESTRATION,
            capabilities=tuple(
                IntegrationCapability(item, destructive=item == "delete") for item in self._capabilities
            ),
        )
        super().__init__(descriptor)
        self._cluster: str | None = None
        self._namespace = "default"

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        self._cluster = profile.options.get("cluster") or profile.endpoint or "default"
        self._namespace = profile.options.get("namespace", "default")
        if profile.options.get("require_credentials", False) and context.get("credential") is None:
            raise PermissionError("kubernetes credentials required")

    async def _disconnect(self) -> None:
        self._cluster = None

    async def _health_check(self) -> HealthReport:
        if self._cluster is None:
            return HealthReport(self.name, ConnectionState.DISCONNECTED, message="cluster not connected")
        return HealthReport(
            self.name,
            ConnectionState.CONNECTED,
            latency_ms=1.0,
            message="kubernetes API reachable",
            details={"cluster": self._cluster, "namespace": self._namespace},
        )

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        if capability == "delete" and not payload.get("approved", False):
            raise PermissionError("owner approval required for kubernetes delete")
        namespace = payload.get("namespace", self._namespace)
        return {
            "provider": "kubernetes",
            "operation": capability,
            "cluster": self._cluster,
            "namespace": namespace,
            "request": dict(payload),
        }
