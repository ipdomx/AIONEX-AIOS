"""Phase 36K healthcare/professional high-stakes control contracts.

These contracts govern administrative, educational, and professional evidence workflows.
They never certify a jurisdictional compliance regime and never authorize autonomous
clinical decisions. High-stakes outputs remain pending until an authorized human review
is recorded by the durable backend authority.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlparse

CaseMode = Literal[
    "administrative",
    "education",
    "professional_assistance",
    "clinical_high_stakes",
]
ResidencyMode = Literal[
    "tenant_default", "region_locked", "country_locked", "local_only"
]


class HighStakesPolicyError(ValueError):
    """A professional/high-stakes request violates a fail-closed policy boundary."""


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    citation_id: str
    title: str
    uri: str
    source_sha256: str

    def validate(self) -> None:
        if not 2 <= len(self.citation_id) <= 80:
            raise HighStakesPolicyError("citation id is outside the allowed range")
        if not 2 <= len(self.title.strip()) <= 400:
            raise HighStakesPolicyError("citation title is outside the allowed range")
        parsed = urlparse(self.uri)
        if parsed.scheme not in {"https", "internal"}:
            raise HighStakesPolicyError(
                "evidence URI must use https or internal scheme"
            )
        digest = self.source_sha256.lower()
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise HighStakesPolicyError("evidence source digest is invalid")


@dataclass(frozen=True, slots=True)
class ProtectedDataProfile:
    profile_id: str
    residency: ResidencyMode
    retention_days: int
    direct_identifiers_allowed: bool = False
    raw_secret_storage_allowed: bool = False
    autonomous_high_stakes_decision_allowed: bool = False

    def validate(self) -> None:
        if not 1 <= self.retention_days <= 3650:
            raise HighStakesPolicyError("retention must be between 1 and 3650 days")
        if self.raw_secret_storage_allowed:
            raise HighStakesPolicyError(
                "raw secrets are never allowed in professional cases"
            )
        if self.autonomous_high_stakes_decision_allowed:
            raise HighStakesPolicyError(
                "autonomous high-stakes decisions are fail-closed"
            )


@dataclass(frozen=True, slots=True)
class ProfessionalEvidencePlan:
    mode: CaseMode
    purpose: str
    subject_ref_hash: str
    residency_profile: str
    retention_until: datetime
    citations: tuple[EvidenceSource, ...]
    evidence_digest: str
    human_review_required: bool
    autonomous_decision_allowed: bool
    compliance_claim: str

    def snapshot(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "purpose": self.purpose,
            "subject_ref_hash": self.subject_ref_hash,
            "residency_profile": self.residency_profile,
            "retention_until": self.retention_until.isoformat(),
            "citations": [asdict(item) for item in self.citations],
            "evidence_digest": self.evidence_digest,
            "human_review_required": self.human_review_required,
            "autonomous_decision_allowed": self.autonomous_decision_allowed,
            "compliance_claim": self.compliance_claim,
        }


def pseudonymous_subject_ref(raw_reference: str, *, tenant_salt: str) -> str:
    reference = raw_reference.strip()
    salt = tenant_salt.strip()
    if len(reference) < 2 or len(salt) < 16:
        raise HighStakesPolicyError("subject reference or tenant salt is too short")
    return hashlib.sha256(f"{salt}\0{reference}".encode()).hexdigest()


def build_professional_evidence_plan(
    *,
    mode: CaseMode,
    purpose: str,
    subject_ref_hash: str,
    profile: ProtectedDataProfile,
    citations: tuple[EvidenceSource, ...],
    issued_at: datetime | None = None,
) -> ProfessionalEvidencePlan:
    profile.validate()
    if mode not in {
        "administrative",
        "education",
        "professional_assistance",
        "clinical_high_stakes",
    }:
        raise HighStakesPolicyError("unsupported professional case mode")
    if not 4 <= len(purpose.strip()) <= 2000:
        raise HighStakesPolicyError("case purpose is outside the allowed range")
    digest = subject_ref_hash.lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise HighStakesPolicyError("subject reference must be a SHA-256 pseudonym")
    if not citations:
        raise HighStakesPolicyError(
            "professional evidence requires at least one citation"
        )
    for citation in citations:
        citation.validate()
    if mode == "clinical_high_stakes" and len(citations) < 2:
        raise HighStakesPolicyError(
            "high-stakes cases require at least two evidence sources"
        )
    canonical = json.dumps(
        [asdict(item) for item in citations], sort_keys=True, separators=(",", ":")
    )
    evidence_digest = hashlib.sha256(canonical.encode()).hexdigest()
    now = issued_at or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return ProfessionalEvidencePlan(
        mode=mode,
        purpose=purpose.strip(),
        subject_ref_hash=digest,
        residency_profile=profile.profile_id,
        retention_until=now + timedelta(days=profile.retention_days),
        citations=citations,
        evidence_digest=evidence_digest,
        human_review_required=mode == "clinical_high_stakes",
        autonomous_decision_allowed=False,
        compliance_claim="configuration-profile-only-not-certification",
    )


def healthcare_administration_blueprint() -> dict[str, object]:
    """Return a non-diagnostic clinic/hospital administration Domain Blueprint."""
    return {
        "roles": [
            "administrator",
            "scheduler",
            "records_officer",
            "professional_reviewer",
            "privacy_officer",
        ],
        "entities": [
            {"name": "person_record", "protected": True, "purpose_limited": True},
            {"name": "appointment", "protected": True, "clinical_decision": False},
            {"name": "document", "protected": True, "provenance_required": True},
            {"name": "review_case", "protected": True, "human_review_required": True},
        ],
        "workflows": [
            "registration-and-consent",
            "appointment-scheduling",
            "records-access-and-audit",
            "professional-evidence-review",
            "retention-and-deletion-review",
        ],
        "excluded_autonomy": [
            "diagnosis",
            "prescription",
            "treatment-selection",
            "clinical-disposition",
        ],
        "compliance": "adapter-required-no-certification-claim",
    }


def compliance_adapter_catalog() -> tuple[dict[str, object], ...]:
    return (
        {
            "id": "generic-regulated",
            "residency_modes": [
                "tenant_default",
                "region_locked",
                "country_locked",
                "local_only",
            ],
            "certified": False,
            "requires_local_legal_validation": True,
        },
        {
            "id": "eu-data-protection-template",
            "residency_modes": ["region_locked", "country_locked"],
            "certified": False,
            "requires_local_legal_validation": True,
        },
        {
            "id": "us-healthcare-privacy-template",
            "residency_modes": ["region_locked", "country_locked"],
            "certified": False,
            "requires_local_legal_validation": True,
        },
    )
