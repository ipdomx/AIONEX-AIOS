from __future__ import annotations

from typing import Any

from .base import BaseInfrastructureIntegration
from .models import (ConnectionProfile, ConnectionState, HealthReport,
                     IntegrationCapability, IntegrationDescriptor, IntegrationKind)


class ObjectStorageProvider(BaseInfrastructureIntegration):
    _capabilities = (
        "buckets", "create_bucket", "delete_bucket", "objects", "put_object", "get_object",
        "delete_object", "copy_object", "presign", "multipart_upload", "usage",
    )

    def __init__(self, name: str = "object_storage") -> None:
        descriptor = IntegrationDescriptor(
            name=name,
            kind=IntegrationKind.STORAGE,
            capabilities=tuple(
                IntegrationCapability(item, destructive=item in {"delete_bucket", "delete_object"})
                for item in self._capabilities
            ),
        )
        super().__init__(descriptor)
        self._endpoint: str | None = None
        self._region: str | None = None

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        self._endpoint = profile.endpoint or profile.options.get("endpoint")
        self._region = profile.options.get("region")
        if profile.options.get("require_credentials", True) and context.get("credential") is None:
            raise PermissionError("object storage credentials required")

    async def _disconnect(self) -> None:
        self._endpoint = None
        self._region = None

    async def _health_check(self) -> HealthReport:
        if self._endpoint is None:
            return HealthReport(self.name, ConnectionState.DISCONNECTED, message="not connected")
        return HealthReport(self.name, ConnectionState.CONNECTED, latency_ms=1.0,
                            message="object storage reachable",
                            details={"endpoint": self._endpoint, "region": self._region})

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        if capability in {"delete_bucket", "delete_object"} and not payload.get("approved", False):
            raise PermissionError(f"owner approval required for {capability}")
        return {
            "provider": "object_storage",
            "operation": capability,
            "endpoint": self._endpoint,
            "region": self._region,
            "request": dict(payload),
        }
