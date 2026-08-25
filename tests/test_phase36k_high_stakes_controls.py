from datetime import UTC, datetime
import pytest
from aios.high_stakes_controls import (
    EvidenceSource,
    HighStakesPolicyError,
    ProtectedDataProfile,
    build_professional_evidence_plan,
    compliance_adapter_catalog,
    healthcare_administration_blueprint,
    pseudonymous_subject_ref,
)


def source(i: int) -> EvidenceSource:
    return EvidenceSource(
        citation_id=f"source-{i}",
        title=f"Evidence source {i}",
        uri=f"https://evidence.invalid/{i}",
        source_sha256=(f"{i:x}" * 64)[:64],
    )


def test_high_stakes_plan_is_human_reviewed_and_pseudonymous() -> None:
    subject = pseudonymous_subject_ref(
        "patient-123", tenant_salt="tenant-salt-0123456789"
    )
    plan = build_professional_evidence_plan(
        mode="clinical_high_stakes",
        purpose="Prepare evidence for an authorized professional reviewer.",
        subject_ref_hash=subject,
        profile=ProtectedDataProfile("country-id", "country_locked", 30),
        citations=(source(1), source(2)),
        issued_at=datetime(2026, 8, 25, tzinfo=UTC),
    )
    assert plan.human_review_required is True
    assert plan.autonomous_decision_allowed is False
    assert plan.compliance_claim == "configuration-profile-only-not-certification"
    assert "patient-123" not in str(plan.snapshot())


def test_high_stakes_plan_rejects_single_source_and_unsafe_policy() -> None:
    subject = "a" * 64
    with pytest.raises(HighStakesPolicyError, match="two evidence"):
        build_professional_evidence_plan(
            mode="clinical_high_stakes",
            purpose="Review a high-stakes professional question.",
            subject_ref_hash=subject,
            profile=ProtectedDataProfile("local", "local_only", 7),
            citations=(source(1),),
        )
    with pytest.raises(HighStakesPolicyError, match="autonomous"):
        ProtectedDataProfile(
            "unsafe", "tenant_default", 30, autonomous_high_stakes_decision_allowed=True
        ).validate()


def test_healthcare_blueprint_excludes_autonomous_clinical_actions() -> None:
    blueprint = healthcare_administration_blueprint()
    assert "appointment-scheduling" in blueprint["workflows"]
    assert {"diagnosis", "prescription", "treatment-selection"}.issubset(
        set(blueprint["excluded_autonomy"])
    )
    assert all(item["certified"] is False for item in compliance_adapter_catalog())
