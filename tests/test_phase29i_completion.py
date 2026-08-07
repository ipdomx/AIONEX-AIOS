import hashlib
import pytest
from aios.phase29i import (
    DistributedJob, DistributedRuntime, IntegrationDefinition, IntegrationState,
    Lifecycle, NonModelIntegrationRegistry, PluginLifecycleService, PluginVersion,
)


def test_plugin_full_lifecycle_signature_permissions_audit_and_rollback():
    svc = PluginLifecycleService(signing_key=b"phase29i-test-signing-key", allowed_permissions={"project.read", "task.write"}, platform_version="1.6.0")
    checksum = hashlib.sha256(b"artifact-v1").hexdigest()
    sig = svc.expected_signature("demo", "1.0.0", checksum)
    svc.submit(PluginVersion("demo", "owner", "1.0.0", checksum, sig, frozenset({"project.read"}), ">=1.6.0", "artifact://demo/1"), "owner")
    svc.approve("demo", "1.0.0", "reviewer")
    svc.publish("demo", "1.0.0", "owner")
    install = svc.install("i1", "org1", "demo", "1.0.0", "admin")
    assert install.state is Lifecycle.ACTIVE
    checksum2 = hashlib.sha256(b"artifact-v2").hexdigest()
    sig2 = svc.expected_signature("demo", "1.1.0", checksum2)
    svc.submit(PluginVersion("demo", "owner", "1.1.0", checksum2, sig2, frozenset({"task.write"}), ">=1.6.0", "artifact://demo/2"), "owner")
    svc.approve("demo", "1.1.0", "reviewer"); svc.publish("demo", "1.1.0", "owner")
    svc.update("i1", "1.1.0", "admin")
    assert svc.rollback("i1", "admin").version == "1.0.0"
    assert svc.disable("i1", "admin").state is Lifecycle.DISABLED
    assert svc.uninstall("i1", "admin").state is Lifecycle.UNINSTALLED
    assert {e.action for e in svc.audit} >= {"plugin.submit", "plugin.approve", "plugin.publish", "plugin.install", "plugin.update", "plugin.rollback", "plugin.disable", "plugin.uninstall"}


def test_plugin_rejects_bad_signature_and_permissions():
    svc = PluginLifecycleService(signing_key=b"phase29i-test-signing-key", allowed_permissions={"safe"}, platform_version="1.6.0")
    with pytest.raises(PermissionError):
        svc.submit(PluginVersion("bad", "o", "1", "x", "bad", frozenset({"root"}), "*", "artifact://bad"), "o")


def test_distributed_runtime_fencing_retry_failover_cancel_and_reconcile():
    rt = DistributedRuntime(); rt.register_worker("a", {"build"}); rt.register_worker("b", {"build"})
    rt.submit(DistributedJob("j1", "build", {})); leased, token = rt.lease("a")
    assert leased.job_id == "j1"
    assert rt.failover("a") == ("j1",)
    with pytest.raises(PermissionError): rt.complete("j1", "a", token)
    leased2, token2 = rt.lease("b"); assert token2 > token
    assert rt.complete("j1", "b", token2).state.value == "succeeded"
    rt.submit(DistributedJob("j2", "build", {})); rt.cancel("j2")
    snapshot = rt.reconcile(); assert snapshot["succeeded"] == 1 and snapshot["cancelled"] == 1


def test_non_model_integrations_truthful_health_and_secret_reference_boundary():
    registry = NonModelIntegrationRegistry()
    for category in sorted(registry.CATEGORIES):
        registry.configure(IntegrationDefinition(category, category, "vault://phase29i/key", "https://example.invalid", True, frozenset({"read"})), "owner")
        assert registry.health(category, probe_ok=True) is IntegrationState.READY
    registry.configure(IntegrationDefinition("missing", "storage", None, "https://example.invalid", True), "owner")
    assert registry.health("missing", probe_ok=True) is IntegrationState.UNCONFIGURED
    assert "vault://phase29i/key" not in registry.snapshot()
    with pytest.raises(ValueError):
        registry.configure(IntegrationDefinition("bad", "calendar", "vault://x", "http://insecure.invalid", True), "owner")
