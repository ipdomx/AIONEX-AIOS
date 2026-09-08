from __future__ import annotations

import pytest

from aios.phase36_identity_media import (
    IdentityMediaPolicyError,
    IdentityMediaRequest,
)

RIGHTS = "a" * 64


def test_fictional_inspired_identity_can_use_free_or_paid_runtime_without_person_rights() -> None:
    for provider_access in ("local_free", "external_free", "paid"):
        decision = IdentityMediaRequest(
            operation="talking_head",
            identity_basis="fictional_inspired",
            provider_access=provider_access,
            subject_reference="persona://retro-pop-host",
            synthetic_media_disclosure_accepted=True,
        ).validate()
        assert decision.allowed is True
        assert decision.rights_required is False
        assert decision.real_person_identity is False
        assert decision.rights_evidence_sha256 is None


def test_fictional_inspired_identity_cannot_claim_a_named_real_person() -> None:
    with pytest.raises(IdentityMediaPolicyError, match="must not bind to a named real person"):
        IdentityMediaRequest(
            operation="lip_sync",
            identity_basis="fictional_inspired",
            provider_access="paid",
            subject_reference="persona://inspired",
            synthetic_media_disclosure_accepted=True,
            named_real_person_reference="real-person://artist",
        ).validate()


def test_consented_real_person_requires_checksum_bound_rights() -> None:
    with pytest.raises(IdentityMediaPolicyError, match="rights evidence"):
        IdentityMediaRequest(
            operation="face_reenactment",
            identity_basis="consented_person",
            provider_access="paid",
            subject_reference="subject://consented-1",
            synthetic_media_disclosure_accepted=True,
        ).validate()

    decision = IdentityMediaRequest(
        operation="face_reenactment",
        identity_basis="consented_person",
        provider_access="paid",
        subject_reference="subject://consented-1",
        synthetic_media_disclosure_accepted=True,
        rights_evidence_sha256=RIGHTS,
        commercial_use_requested=True,
        commercial_use_authorized=True,
    ).validate()
    assert decision.rights_required is True
    assert decision.rights_evidence_sha256 == RIGHTS


def test_licensed_public_figure_requires_licensed_catalog_rights_and_identity_declaration() -> None:
    with pytest.raises(IdentityMediaPolicyError, match="licensed-catalog"):
        IdentityMediaRequest(
            operation="voice_clone",
            identity_basis="licensed_public_figure",
            provider_access="paid",
            subject_reference="licensed://artist-1",
            synthetic_media_disclosure_accepted=True,
            rights_evidence_sha256=RIGHTS,
            license_reference="license://catalog/artist-1",
            named_real_person_reference="artist-1",
            claims_real_identity=True,
        ).validate()

    decision = IdentityMediaRequest(
        operation="voice_clone",
        identity_basis="licensed_public_figure",
        provider_access="licensed_catalog",
        subject_reference="licensed://artist-1",
        synthetic_media_disclosure_accepted=True,
        rights_evidence_sha256=RIGHTS,
        license_reference="license://catalog/artist-1",
        named_real_person_reference="artist-1",
        claims_real_identity=True,
    ).validate()
    public = decision.public_snapshot()
    assert public["allowed"] is True
    assert public["rights_evidence_present"] is True
    assert public["license_reference_present"] is True
    assert "rights_evidence_sha256" not in public
    assert "license_reference" not in public


def test_commercial_identity_media_requires_explicit_commercial_authorization() -> None:
    with pytest.raises(IdentityMediaPolicyError, match="commercial use"):
        IdentityMediaRequest(
            operation="avatar_generation",
            identity_basis="self",
            provider_access="local_free",
            subject_reference="subject://self",
            synthetic_media_disclosure_accepted=True,
            rights_evidence_sha256=RIGHTS,
            commercial_use_requested=True,
            commercial_use_authorized=False,
        ).validate()
