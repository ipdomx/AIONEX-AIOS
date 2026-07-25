from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import BaseInfrastructureIntegration
from .models import (ConnectionProfile, ConnectionState, HealthReport,
                     IntegrationCapability, IntegrationDescriptor, IntegrationKind)


@dataclass(frozen=True, slots=True)
class CloudResource:
    provider: str
    resource_type: str
    resource_id: str
    name: str
    region: str | None = None
    status: str = "unknown"
    metadata: dict[str, Any] | None = None


class BaseCloudProvider(BaseInfrastructureIntegration):
    provider_name = "cloud"
    default_endpoint: str | None = None
    capabilities: tuple[str, ...] = (
        "regions", "instances", "create_instance", "delete_instance", "start_instance",
        "stop_instance", "reboot_instance", "networks", "firewalls", "volumes",
        "snapshots", "object_storage", "account",
    )

    def __init__(self, name: str | None = None) -> None:
        integration_name = name or self.provider_name
        destructive = {"delete_instance"}
        descriptor = IntegrationDescriptor(
            name=integration_name,
            kind=IntegrationKind.CLOUD,
            capabilities=tuple(
                IntegrationCapability(capability, destructive=capability in destructive)
                for capability in self.capabilities
            ),
            metadata={"provider": self.provider_name},
        )
        super().__init__(descriptor)
        self._endpoint: str | None = None
        self._context: dict[str, Any] = {}

    async def _connect(self, profile: ConnectionProfile, context: dict[str, Any]) -> None:
        self._endpoint = profile.endpoint or self.default_endpoint
        self._context = dict(context)
        if profile.options.get("require_credentials", True):
            credential = context.get("credential")
            if credential is None and not profile.options.get("anonymous", False):
                raise PermissionError(f"credentials required for {self.provider_name}")

    async def _disconnect(self) -> None:
        self._endpoint = None
        self._context.clear()

    async def _health_check(self) -> HealthReport:
        if self._endpoint is None:
            return HealthReport(self.name, ConnectionState.DISCONNECTED, message="not connected")
        return HealthReport(
            self.name,
            ConnectionState.CONNECTED,
            latency_ms=1.0,
            message=f"{self.provider_name} control plane reachable",
            details={"endpoint": self._endpoint},
        )

    async def _execute(self, capability: str, payload: dict[str, Any]) -> Any:
        if capability == "delete_instance" and not payload.get("approved", False):
            raise PermissionError("owner approval required for instance deletion")
        return {
            "provider": self.provider_name,
            "operation": capability,
            "endpoint": self._endpoint,
            "request": dict(payload),
        }


class DigitalOceanProvider(BaseCloudProvider):
    provider_name = "digitalocean"
    default_endpoint = "https://api.digitalocean.com/v2"
    capabilities = BaseCloudProvider.capabilities + (
        "droplets", "images", "domains", "load_balancers", "kubernetes_clusters",
    )


class AWSProvider(BaseCloudProvider):
    provider_name = "aws"
    default_endpoint = "https://aws.amazon.com"
    capabilities = BaseCloudProvider.capabilities + (
        "ec2", "s3", "iam", "rds", "eks", "cloudwatch", "route53",
    )


class AzureProvider(BaseCloudProvider):
    provider_name = "azure"
    default_endpoint = "https://management.azure.com"
    capabilities = BaseCloudProvider.capabilities + (
        "virtual_machines", "blob_storage", "resource_groups", "aks", "monitor", "dns_zones",
    )


class GCPProvider(BaseCloudProvider):
    provider_name = "gcp"
    default_endpoint = "https://cloudresourcemanager.googleapis.com"
    capabilities = BaseCloudProvider.capabilities + (
        "compute", "cloud_storage", "projects", "gke", "cloud_sql", "cloud_dns", "monitoring",
    )
