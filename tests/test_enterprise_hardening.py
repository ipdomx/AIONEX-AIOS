from datetime import datetime, timedelta, timezone

from aios.enterprise_hardening.access_review import AccessGrant, AccessReviewService, ReviewDecision
from aios.enterprise_hardening.compliance import ComplianceControl, ComplianceRegistry, ControlStatus
from aios.enterprise_hardening.resilience_gate import EnterpriseResilienceGate, ResilienceEvidence
from aios.enterprise_hardening.security_policy import SecurityLevel, SecurityPolicy, SecurityPolicyEngine
from aios.enterprise_hardening.secrets_governance import SecretRecord, SecretsGovernanceService


def test_security_policy_blocks_services_and_regions() -> None:
    engine = SecurityPolicyEngine()
    engine.set_policy(
        SecurityPolicy(
            owner_id="owner-1",
            level=SecurityLevel.CRITICAL,
            allowed_regions={"eu-central"},
            blocked_services={"unsafe-provider"},
        )
    )

    engine.assert_service_allowed("owner-1", "github")
    engine.assert_region_allowed("owner-1", "eu-central")

    try:
        engine.assert_service_allowed("owner-1", "unsafe-provider")
    except PermissionError:
        pass
    else:
        raise AssertionError("blocked services must be rejected")


def test_compliance_requires_evidence_before_verification() -> None:
    registry = ComplianceRegistry()
    registry.register(
        ComplianceControl(
            control_id="ctl-1",
            owner_id="owner-1",
            framework="ISO27001",
            title="Access review",
        )
    )

    try:
        registry.set_status("ctl-1", "owner-1", ControlStatus.VERIFIED)
    except ValueError:
        pass
    else:
        raise AssertionError("verification without evidence must fail")

    registry.add_evidence("ctl-1", "owner-1", "audit/access-review.json")
    control = registry.set_status("ctl-1", "owner-1", ControlStatus.VERIFIED)
    assert control.status is ControlStatus.VERIFIED


def test_secret_rotation_and_revocation() -> None:
    service = SecretsGovernanceService()
    old = datetime.now(timezone.utc) - timedelta(days=120)
    service.register(
        SecretRecord(
            secret_id="secret-1",
            owner_id="owner-1",
            provider="stripe",
            created_at=old,
            rotation_days=90,
        )
    )
    assert service.due_for_rotation("owner-1")
    service.rotate("secret-1", "owner-1")
    assert not service.due_for_rotation("owner-1")
    service.revoke("secret-1", "owner-1")


def test_access_review_decisions_are_immutable() -> None:
    service = AccessReviewService()
    service.register(
        AccessGrant(
            grant_id="grant-1",
            owner_id="owner-1",
            principal_id="admin-1",
            permission="platform.admin",
            privileged=True,
        )
    )
    result = service.decide("grant-1", "owner-1", ReviewDecision.APPROVED, "ticket-17")
    assert result.decision is ReviewDecision.APPROVED
    try:
        service.decide("grant-1", "owner-1", ReviewDecision.REVOKED, "ticket-18")
    except RuntimeError:
        pass
    else:
        raise AssertionError("final access decisions must be immutable")


def test_resilience_gate_requires_all_evidence() -> None:
    gate = EnterpriseResilienceGate()
    evidence = ResilienceEvidence(owner_id="owner-1", backup_verified=True)
    assert "restore_verified" in gate.validate(evidence)

    ready = ResilienceEvidence(
        owner_id="owner-1",
        backup_verified=True,
        restore_verified=True,
        failover_verified=True,
        disaster_recovery_verified=True,
        load_test_verified=True,
        security_validation_verified=True,
    )
    gate.assert_ready(ready)
