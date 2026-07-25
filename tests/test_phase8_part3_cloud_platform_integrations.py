import asyncio

import pytest

from aios.infrastructure import (AWSProvider, AzureProvider, CloudflareProvider, ConnectionProfile,
                                 Credential, DigitalOceanProvider, GCPProvider,
                                 InfrastructurePlatform, KubernetesProvider, ObjectStorageProvider)


def make_platform():
    platform = InfrastructurePlatform(b"0123456789abcdef")
    platform.credentials.register("cloud", Credential(token="secret"))
    return platform


def connect(platform, profile):
    platform.connections.register_profile(profile)
    asyncio.run(platform.connections.connect(profile.name))


def test_cloud_providers_register_and_execute():
    platform = make_platform()
    providers = [DigitalOceanProvider(), AWSProvider(), AzureProvider(), GCPProvider()]
    for provider in providers:
        platform.registry.register(provider)
        connect(platform, ConnectionProfile(name=f"{provider.name}-main", integration=provider.name,
                                            credential_ref="cloud"))
        result = asyncio.run(platform.connections.execute(f"{provider.name}-main", "regions", {}))
        assert result["provider"] == provider.provider_name
        assert result["operation"] == "regions"


def test_cloud_delete_requires_owner_approval():
    platform = make_platform()
    platform.registry.register(DigitalOceanProvider())
    connect(platform, ConnectionProfile(name="do", integration="digitalocean", credential_ref="cloud"))
    with pytest.raises(PermissionError):
        asyncio.run(platform.connections.execute("do", "delete_instance", {"id": "vm-1"}))
    result = asyncio.run(platform.connections.execute(
        "do", "delete_instance", {"id": "vm-1", "approved": True}))
    assert result["operation"] == "delete_instance"


def test_kubernetes_operations_and_health():
    platform = make_platform()
    platform.registry.register(KubernetesProvider())
    connect(platform, ConnectionProfile(name="cluster", integration="kubernetes",
                                        options={"cluster": "production", "namespace": "aios"}))
    result = asyncio.run(platform.connections.execute("cluster", "deployments", {}))
    assert result["cluster"] == "production"
    assert result["namespace"] == "aios"
    report = asyncio.run(platform.registry.get("kubernetes").health_check())
    assert report.details["cluster"] == "production"


def test_cloudflare_dns_and_approval():
    platform = make_platform()
    platform.registry.register(CloudflareProvider())
    connect(platform, ConnectionProfile(name="dns", integration="cloudflare", credential_ref="cloud"))
    result = asyncio.run(platform.connections.execute("dns", "dns_records", {"zone": "example.com"}))
    assert result["provider"] == "cloudflare"
    with pytest.raises(PermissionError):
        asyncio.run(platform.connections.execute("dns", "delete_dns_record", {"id": "record"}))


def test_object_storage_operations():
    platform = make_platform()
    platform.registry.register(ObjectStorageProvider())
    connect(platform, ConnectionProfile(name="storage", integration="object_storage",
                                        endpoint="https://objects.example", credential_ref="cloud",
                                        options={"region": "fra1"}))
    result = asyncio.run(platform.connections.execute(
        "storage", "put_object", {"bucket": "backups", "key": "snapshot.tar"}))
    assert result["region"] == "fra1"
    assert result["operation"] == "put_object"
