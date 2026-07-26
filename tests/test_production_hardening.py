from aios.production_hardening import (
    AuditEvent,
    ComponentHealth,
    EnvironmentConfig,
    HealthStatus,
    ProductionHardeningPlatform,
    RetryPolicy,
)
from aios.production_hardening.config import DeploymentEnvironment
from aios.production_hardening.resilience import CircuitBreaker, CircuitState


def test_production_hardening_readiness_and_audit() -> None:
    platform = ProductionHardeningPlatform.build_default()
    platform.health.report(ComponentHealth(component="database", status=HealthStatus.HEALTHY))
    platform.health.report(ComponentHealth(component="api", status=HealthStatus.HEALTHY))

    config = EnvironmentConfig(
        environment=DeploymentEnvironment.PRODUCTION,
        debug=False,
        secret_provider="vault",
        database_url="postgresql://service/db",
        allowed_hosts=("aios.example",),
        tls_required=True,
    )
    report = platform.readiness.evaluate(config, required_components=("database", "api"))
    assert report.ready is True

    platform.audit.append(
        AuditEvent(
            event_id="evt-1",
            actor_id="owner-1",
            action="deployment.approve",
            resource="release:3.2.0-beta.1",
            outcome="approved",
            correlation_id="corr-1",
        )
    )
    assert platform.audit.count() == 1
    assert platform.audit.query(correlation_id="corr-1")[0].outcome == "approved"
    assert platform.validate()["ready"] is True


def test_retry_policy_and_circuit_breaker() -> None:
    attempts = {"count": 0}

    def unstable() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        return "ok"

    assert RetryPolicy(attempts=3).execute(unstable) == "ok"

    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout_seconds=60)
    for _ in range(2):
        try:
            breaker.execute(lambda: (_ for _ in ()).throw(RuntimeError("failure")))
        except RuntimeError:
            pass
    assert breaker.state is CircuitState.OPEN
    assert breaker.allow_request() is False
