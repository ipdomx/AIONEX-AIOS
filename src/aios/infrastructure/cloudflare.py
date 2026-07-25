from __future__ import annotations

from typing import Any

from .base import BaseInfrastructureIntegration
from .models import (ConnectionProfile, ConnectionState, HealthReport,
                     IntegrationCapability, IntegrationDescriptor, IntegrationKind)


class CloudflareProvider(BaseInfrastructureIntegration):
    _capabilities = (
        "accounts", "zones", "dns_records", "create_dns_record", "update_dns_record",
        "delete_dns_record", "purge_cache", "firewall_rules", "workers", "r2_buckets",
        "tunnels", "load_balancers", "analytics",
    )

    def __init__(self, name: str = "cloudflare") -> None:
        descriptor = IntegrationDescriptor(
            name=name,
            kind=IntegrationKind.DNS,
            capabilities=tuple(
                IntegrationCapability(item, destructive=item in {"delete_dns_record", "purge_cache"})
                for item in self._capabilities
            ),
        )
        super().__init__(descriptor)
        self._endpoint: str | None = None

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        if context.get("credential") is None and not profile.options.get("anonymous", False):
            raise PermissionError("cloudflare API token required")
        self._endpoint = profile.endpoint or "https://api.cloudflare.com/client/v4"

    async def _disconnect(self) -> None:
        self._endpoint = None

    async def _health_check(self) -> HealthReport:
        if self._endpoint is None:
            return HealthReport(self.name, ConnectionState.DISCONNECTED, message="not connected")
        return HealthReport(self.name, ConnectionState.CONNECTED, latency_ms=1.0,
                            message="cloudflare API reachable", details={"endpoint": self._endpoint})

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        if capability in {"delete_dns_record", "purge_cache"} and not payload.get("approved", False):
            raise PermissionError(f"owner approval required for {capability}")
        return {
            "provider": "cloudflare",
            "operation": capability,
            "endpoint": self._endpoint,
            "request": dict(payload),
        }
