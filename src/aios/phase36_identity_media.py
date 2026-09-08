from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

IdentityBasis = Literal[
    "self",
    "consented_person",
    "licensed_public_figure",
    "fictional_inspired",
]
IdentityOperation = Literal[
    "voice_clone",
    "voice_transform",
    "face_reenactment",
    "face_swap",
    "talking_head",
    "lip_sync",
    "avatar_generation",
]
ProviderAccess = Literal[
    "local_free",
    "external_free",
    "paid",
    "licensed_catalog",
]

_ALLOWED_BASES = {
    "self",
    "consented_person",
    "licensed_public_figure",
    "fictional_inspired",
}
_ALLOWED_OPERATIONS = {
    "voice_clone",
    "voice_transform",
    "face_reenactment",
    "face_swap",
    "talking_head",
    "lip_sync",
    "avatar_generation",
}
_ALLOWED_PROVIDER_ACCESS = {
    "local_free",
    "external_free",
    "paid",
    "licensed_catalog",
}


class IdentityMediaPolicyError(ValueError):
    """Identity-media request cannot be admitted under the governed rights contract."""


def _sha256(value: str | None, *, required: bool) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        if required:
            raise IdentityMediaPolicyError("rights evidence SHA-256 is required")
        return None
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise IdentityMediaPolicyError("rights evidence SHA-256 must be 64 hexadecimal characters")
    return normalized


def _required(value: str | None, *, label: str, maximum: int = 500) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise IdentityMediaPolicyError(f"{label} is required")
    if len(normalized) > maximum:
        raise IdentityMediaPolicyError(f"{label} exceeds the supported length")
    return normalized


@dataclass(frozen=True, slots=True)
class IdentityMediaRequest:
    operation: IdentityOperation
    identity_basis: IdentityBasis
    provider_access: ProviderAccess
    subject_reference: str
    synthetic_media_disclosure_accepted: bool
    rights_evidence_sha256: str | None = None
    license_reference: str | None = None
    commercial_use_requested: bool = False
    commercial_use_authorized: bool = False
    claims_real_identity: bool = False
    named_real_person_reference: str | None = None

    def validate(self) -> "IdentityMediaDecision":
        if self.operation not in _ALLOWED_OPERATIONS:
            raise IdentityMediaPolicyError("unsupported identity-media operation")
        if self.identity_basis not in _ALLOWED_BASES:
            raise IdentityMediaPolicyError("unsupported identity basis")
        if self.provider_access not in _ALLOWED_PROVIDER_ACCESS:
            raise IdentityMediaPolicyError("unsupported provider access class")
        subject = _required(self.subject_reference, label="subject reference", maximum=200)
        if not self.synthetic_media_disclosure_accepted:
            raise IdentityMediaPolicyError("synthetic media disclosure must be accepted")
        if self.commercial_use_requested and not self.commercial_use_authorized:
            raise IdentityMediaPolicyError("commercial use requires explicit authorization")

        real_person = self.identity_basis != "fictional_inspired"
        rights_required = real_person
        rights_hash = _sha256(self.rights_evidence_sha256, required=rights_required)
        license_ref = str(self.license_reference or "").strip() or None
        named_ref = str(self.named_real_person_reference or "").strip() or None

        if self.identity_basis == "licensed_public_figure":
            if self.provider_access != "licensed_catalog":
                raise IdentityMediaPolicyError(
                    "licensed public-figure identity requires a licensed-catalog provider route"
                )
            license_ref = _required(license_ref, label="license reference", maximum=500)
            if not named_ref:
                raise IdentityMediaPolicyError("licensed public-figure identity requires a named subject reference")
            if not self.claims_real_identity:
                raise IdentityMediaPolicyError(
                    "licensed public-figure route must explicitly declare that it represents the licensed identity"
                )

        if self.identity_basis in {"self", "consented_person"} and self.claims_real_identity is False:
            # The user may still render an avatarized form of the authorized subject.  The
            # rights evidence remains mandatory even when the output is stylized.
            pass

        if self.identity_basis == "fictional_inspired":
            if self.claims_real_identity:
                raise IdentityMediaPolicyError(
                    "fictional/inspired identity must not be presented as a real person's identity"
                )
            if named_ref:
                raise IdentityMediaPolicyError(
                    "fictional/inspired identity must not bind to a named real person"
                )
            if license_ref:
                raise IdentityMediaPolicyError(
                    "fictional/inspired identity must not claim a real-person license reference"
                )

        return IdentityMediaDecision(
            allowed=True,
            operation=self.operation,
            identity_basis=self.identity_basis,
            provider_access=self.provider_access,
            subject_reference=subject,
            rights_required=rights_required,
            rights_evidence_sha256=rights_hash,
            license_reference=license_ref,
            commercial_use_authorized=(
                self.commercial_use_authorized if self.commercial_use_requested else None
            ),
            synthetic_media_disclosure_required=True,
            named_real_person_reference=named_ref,
            real_person_identity=real_person,
        )


@dataclass(frozen=True, slots=True)
class IdentityMediaDecision:
    allowed: bool
    operation: IdentityOperation
    identity_basis: IdentityBasis
    provider_access: ProviderAccess
    subject_reference: str
    rights_required: bool
    rights_evidence_sha256: str | None
    license_reference: str | None
    commercial_use_authorized: bool | None
    synthetic_media_disclosure_required: bool
    named_real_person_reference: str | None
    real_person_identity: bool

    def public_snapshot(self) -> dict[str, object]:
        payload = asdict(self)
        payload["rights_evidence_present"] = self.rights_evidence_sha256 is not None
        payload.pop("rights_evidence_sha256", None)
        payload["license_reference_present"] = self.license_reference is not None
        payload.pop("license_reference", None)
        return payload
