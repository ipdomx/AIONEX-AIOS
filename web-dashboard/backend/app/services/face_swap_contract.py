"""Fail-closed Face Swap contract owned by FR-12.

This module is intentionally provider-neutral at the execution boundary. It
records the exact two-image, rights, idempotency and output invariants that a
cross-scope runtime integration must satisfy before face_swap can become
runtime-ready.

It does not make provider calls, read credentials, grant Owner permission or
mark the operation live.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

FACE_SWAP_OPERATION = "face_swap"
FACE_SWAP_PROVIDER = "replicate"
FACE_SWAP_MODEL = "codeplugtech/face-swap"
FACE_SWAP_MODEL_VERSION = (
    "278a81e7ebb22db98bcba54de985d22cc1abeead2754eb1f2af717247be69b34"
)
FACE_SWAP_PREDICTION_ENDPOINT = "https://api.replicate.com/v1/predictions"

FACE_SWAP_MAX_ATTEMPTS = 1
FACE_SWAP_AMBIGUOUS_SUBMISSION_REPLAY = False
FACE_SWAP_RUNTIME_APPROVED = False

ALLOWED_IMAGE_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
REAL_PERSON_BASES = frozenset({"self", "consented_person", "licensed_public_figure"})
IDENTITY_BASES = REAL_PERSON_BASES | {"fictional_inspired"}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")


class FaceSwapContractError(ValueError):
    """A fail-closed Face Swap contract violation."""


def _sha256(value: str, *, field: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise FaceSwapContractError(f"{field}-invalid")
    return text


def _bounded_text(value: str, *, field: str, maximum: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum:
        raise FaceSwapContractError(f"{field}-invalid")
    return text


def _storage_key(value: str) -> str:
    text = _bounded_text(value, field="storage-key", maximum=1024)
    if text.startswith("/") or "\\" in text or any(part == ".." for part in text.split("/")):
        raise FaceSwapContractError("storage-key-invalid")
    return text


def _cost(value: float | int | str | Decimal) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise FaceSwapContractError("approved-max-cost-invalid") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("1000"):
        raise FaceSwapContractError("approved-max-cost-invalid")
    return amount.quantize(Decimal("0.000001"))


@dataclass(frozen=True, slots=True)
class FaceSwapStoredInput:
    """One private, execution-scoped visual input."""

    input_name: Literal["target_image", "source_face"]
    storage_key: str
    checksum_sha256: str
    content_type: str
    filename: str

    def __post_init__(self) -> None:
        if self.input_name not in {"target_image", "source_face"}:
            raise FaceSwapContractError("input-name-invalid")
        object.__setattr__(self, "storage_key", _storage_key(self.storage_key))
        object.__setattr__(
            self,
            "checksum_sha256",
            _sha256(self.checksum_sha256, field=f"{self.input_name}-checksum"),
        )
        media = str(self.content_type or "").strip().lower()
        if media not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise FaceSwapContractError(f"{self.input_name}-content-type-rejected")
        object.__setattr__(self, "content_type", media)
        name = _bounded_text(self.filename, field=f"{self.input_name}-filename", maximum=160)
        if name != name.rsplit("/", 1)[-1] or name != name.rsplit("\\", 1)[-1]:
            raise FaceSwapContractError(f"{self.input_name}-filename-invalid")
        object.__setattr__(self, "filename", name)


@dataclass(frozen=True, slots=True)
class FaceSwapAuthorization:
    """Rights and Owner controls bound to the requested face identity."""

    identity_basis: Literal[
        "self", "consented_person", "licensed_public_figure", "fictional_inspired"
    ]
    subject_reference: str
    rights_evidence_sha256: str | None
    owner_approval_version: int | None
    synthetic_media_disclosure_accepted: bool

    def __post_init__(self) -> None:
        basis = str(self.identity_basis or "").strip().lower()
        if basis not in IDENTITY_BASES:
            raise FaceSwapContractError("identity-basis-invalid")
        object.__setattr__(self, "identity_basis", basis)
        subject = _bounded_text(
            self.subject_reference,
            field="subject-reference",
            maximum=200,
        )
        object.__setattr__(self, "subject_reference", subject)
        if not self.synthetic_media_disclosure_accepted:
            raise FaceSwapContractError("synthetic-media-disclosure-required")

        if basis in REAL_PERSON_BASES:
            if self.owner_approval_version is None or int(self.owner_approval_version) < 1:
                raise FaceSwapContractError("owner-approval-required")
            object.__setattr__(self, "owner_approval_version", int(self.owner_approval_version))
            if not self.rights_evidence_sha256:
                raise FaceSwapContractError("rights-evidence-required")
            object.__setattr__(
                self,
                "rights_evidence_sha256",
                _sha256(self.rights_evidence_sha256, field="rights-evidence"),
            )
        elif self.rights_evidence_sha256:
            object.__setattr__(
                self,
                "rights_evidence_sha256",
                _sha256(self.rights_evidence_sha256, field="rights-evidence"),
            )


@dataclass(frozen=True, slots=True)
class FaceSwapExecutionContract:
    """Immutable FR-12 admission contract before provider submission."""

    execution_id: str
    organization_id: str
    project_id: str | None
    idempotency_key: str
    target_image: FaceSwapStoredInput
    source_face: FaceSwapStoredInput
    authorization: FaceSwapAuthorization
    approved_max_cost_usd: Decimal | float | int | str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "execution_id",
            _bounded_text(self.execution_id, field="execution-id", maximum=80),
        )
        object.__setattr__(
            self,
            "organization_id",
            _bounded_text(self.organization_id, field="organization-id", maximum=80),
        )
        if self.project_id is not None:
            project = str(self.project_id).strip()
            if not project or len(project) > 80:
                raise FaceSwapContractError("project-id-invalid")
            object.__setattr__(self, "project_id", project)
        idem = str(self.idempotency_key or "").strip()
        if not _IDEMPOTENCY_RE.fullmatch(idem):
            raise FaceSwapContractError("idempotency-key-invalid")
        object.__setattr__(self, "idempotency_key", idem)

        if self.target_image.input_name != "target_image":
            raise FaceSwapContractError("target-image-contract-invalid")
        if self.source_face.input_name != "source_face":
            raise FaceSwapContractError("source-face-contract-invalid")
        object.__setattr__(self, "approved_max_cost_usd", _cost(self.approved_max_cost_usd))

    @property
    def operation(self) -> str:
        return FACE_SWAP_OPERATION

    @property
    def provider_runtime_approved(self) -> bool:
        return FACE_SWAP_RUNTIME_APPROVED

    @property
    def max_attempts(self) -> int:
        return FACE_SWAP_MAX_ATTEMPTS

    @property
    def ambiguous_submission_replay(self) -> bool:
        return FACE_SWAP_AMBIGUOUS_SUBMISSION_REPLAY


@dataclass(frozen=True, slots=True)
class FaceSwapOutputEvidence:
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    suffix: Literal[".png", ".jpg", ".webp"]
    checksum_sha256: str
    size_bytes: int


def validate_output_image(
    body: bytes,
    content_type: str,
    *,
    max_bytes: int = 64 * 1024 * 1024,
) -> FaceSwapOutputEvidence:
    """Verify the binary image envelope before private output persistence."""

    if not body or len(body) > int(max_bytes):
        raise FaceSwapContractError("output-size-rejected")
    media = str(content_type or "").split(";", 1)[0].strip().lower()

    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        detected, suffix = "image/png", ".png"
    elif len(body) >= 3 and body[:3] == b"\xff\xd8\xff":
        detected, suffix = "image/jpeg", ".jpg"
    elif len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        detected, suffix = "image/webp", ".webp"
    else:
        raise FaceSwapContractError("output-image-envelope-rejected")

    if media != detected:
        raise FaceSwapContractError("output-content-type-mismatch")
    return FaceSwapOutputEvidence(
        media_type=detected,
        suffix=suffix,
        checksum_sha256=hashlib.sha256(body).hexdigest(),
        size_bytes=len(body),
    )
