import asyncio

from aios.infrastructure import (ConnectionProfile, ConnectionState, Credential,
                                 InfrastructurePlatform, InMemoryIntegration,
                                 IntegrationCapability, IntegrationDescriptor,
                                 IntegrationKind)


def integration():
    return InMemoryIntegration(IntegrationDescriptor(
        name="ssh", kind=IntegrationKind.SSH,
        capabilities=(IntegrationCapability("execute"), IntegrationCapability("upload")),
    ))


def test_registry_discovery_and_config_loading():
    platform = InfrastructurePlatform(b"0123456789abcdef")
    platform.registry.register(integration())
    profiles = platform.config.load_mapping({"connections": {
        "server": {"integration": "ssh", "endpoint": "host", "options": {"port": 22}}
    }})
    platform.load_profiles(profiles)
    assert platform.registry.discover("execute")[0].name == "ssh"
    assert platform.connections.profile("server").options["port"] == 22


def test_secrets_are_encrypted_and_rotate():
    platform = InfrastructurePlatform(b"0123456789abcdef")
    first = platform.vault.put("api/key", "secret-one")
    second = platform.vault.put("api/key", "secret-two")
    assert platform.vault.get("api/key") == "secret-two"
    assert first.version == 1 and second.version == 2
    assert second.rotated_at is not None


def test_credentials_are_resolved_without_plaintext_registry_storage():
    platform = InfrastructurePlatform(b"0123456789abcdef")
    platform.credentials.register("root", Credential(username="root", password="p", private_key="k"))
    resolved = platform.credentials.resolve("root")
    assert resolved.password == "p" and resolved.private_key == "k"
    assert platform.credentials.redacted("root")["password"] == "***"


def test_connection_lifecycle_execution_and_secret_context():
    platform = InfrastructurePlatform(b"0123456789abcdef")
    adapter = integration()
    platform.registry.register(adapter)
    platform.credentials.register("root", Credential(username="root", password="pass"))
    platform.vault.put("hosts/server/fingerprint", "abc")
    platform.connections.register_profile(ConnectionProfile(
        name="server", integration="ssh", endpoint="host", credential_ref="root",
        secret_refs={"fingerprint": "hosts/server/fingerprint"},
    ))
    asyncio.run(platform.connections.connect("server"))
    result = asyncio.run(platform.connections.execute("server", "execute", {"command": "true"}))
    assert adapter.state == ConnectionState.CONNECTED
    assert adapter.context["credential"].password == "pass"
    assert adapter.context["secrets"]["fingerprint"] == "abc"
    assert result["capability"] == "execute"
    asyncio.run(platform.connections.disconnect("server"))
    assert adapter.state == ConnectionState.DISCONNECTED


def test_health_monitor_snapshot():
    platform = InfrastructurePlatform(b"0123456789abcdef")
    platform.registry.register(integration())
    reports = asyncio.run(platform.health.check_all())
    assert reports[0].state == ConnectionState.DISCONNECTED
    assert platform.health.snapshot()["ssh"]["state"] == "disconnected"
