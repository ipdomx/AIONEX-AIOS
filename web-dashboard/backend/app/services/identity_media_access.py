"""Per-user Super Owner access control for governed identity media.

Real-person identity operations are deny-by-default until the Super Owner grants
that exact operation to the user. Fictional/non-identical identity media is
available by default when a runtime route is live. Owner deny always wins.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import AuditEvent, OwnerControlRecord, User
from app.services import billing

ACCESS_DOMAIN = "identity-media-user-access"
REQUEST_DOMAIN = "identity-media-access-request"
OPERATIONS = (
    "voice_clone",
    "voice_transform",
    "face_reenactment",
    "face_swap",
    "talking_head",
    "lip_sync",
    "avatar_generation",
)
IDENTITY_BASES = (
    "self",
    "consented_person",
    "licensed_public_figure",
    "fictional_inspired",
)
REAL_PERSON_BASES = frozenset({"self", "consented_person", "licensed_public_figure"})
RUNTIME_READY_OPERATIONS = frozenset({"voice_clone", "face_reenactment", "talking_head", "lip_sync", "avatar_generation"})


@dataclass(frozen=True, slots=True)
class IdentityMediaAccessDecision:
    operation: str
    identity_basis: str
    allowed: bool
    owner_approval_required: bool
    source: str
    reason: str
    runtime_ready: bool
    override_version: int | None = None
    subject_scope: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "identity_basis": self.identity_basis,
            "allowed": self.allowed,
            "owner_approval_required": self.owner_approval_required,
            "source": self.source,
            "reason": self.reason,
            "runtime_ready": self.runtime_ready,
            "override_version": self.override_version,
            "subject_scope": self.subject_scope,
        }


def _now() -> datetime:
    return datetime.now(UTC)


def _require_super_owner(actor: UserRecord) -> None:
    if actor.role != "Super Owner":
        raise ValueError("super-owner-required")


def _operation(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in OPERATIONS:
        raise ValueError("unknown-identity-media-operation")
    return normalized


def _basis(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in IDENTITY_BASES:
        raise ValueError("unknown-identity-basis")
    return normalized


def _subject(value: str | None, *, required: bool = False) -> str | None:
    normalized = str(value or "").strip()
    if required and not normalized:
        raise ValueError("subject-reference-required")
    if len(normalized) > 200:
        raise ValueError("subject-reference-too-long")
    return normalized or None


def _access_resource(user_id: str, operation: str) -> str:
    return f"user:{user_id}:{operation}"


async def _access_record(
    session: AsyncSession, *, user_id: str, operation: str
) -> OwnerControlRecord | None:
    return await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == ACCESS_DOMAIN,
            OwnerControlRecord.resource_id == _access_resource(user_id, operation),
            OwnerControlRecord.status == "active",
        )
    )


def _subject_matches(payload: dict[str, Any], subject_reference: str | None) -> bool:
    scope = str(payload.get("subject_scope") or "any").strip().lower()
    if scope == "any":
        return True
    if scope != "exact":
        return False
    expected = str(payload.get("subject_reference") or "").strip().casefold()
    actual = str(subject_reference or "").strip().casefold()
    return bool(expected and actual and expected == actual)


async def effective_access(
    session: AsyncSession,
    actor: UserRecord,
    *,
    operation: str,
    identity_basis: str,
    subject_reference: str | None = None,
) -> IdentityMediaAccessDecision:
    op = _operation(operation)
    basis = _basis(identity_basis)
    runtime_ready = op in RUNTIME_READY_OPERATIONS and basis != "licensed_public_figure"
    if actor.status not in {"active", "online"}:
        return IdentityMediaAccessDecision(op, basis, False, basis in REAL_PERSON_BASES, "account", "user-inactive", runtime_ready)
    context = await billing.billing_context(session, actor.organization_id)
    account = context["account"]
    if account.status not in billing.ACTIVE_ACCOUNT_STATUSES:
        return IdentityMediaAccessDecision(op, basis, False, basis in REAL_PERSON_BASES, "billing", "account-suspended", runtime_ready)

    record = await _access_record(session, user_id=actor.id, operation=op)
    if record is not None:
        payload = dict(record.payload or {})
        allowed = bool(record.enabled and payload.get("allowed", True))
        bases = {str(item) for item in (payload.get("identity_bases") or [])}
        basis_allowed = basis in bases if bases else False
        subject_allowed = _subject_matches(payload, subject_reference)
        if not allowed:
            return IdentityMediaAccessDecision(op, basis, False, basis in REAL_PERSON_BASES, "owner-override", "owner-deny", runtime_ready, record.version, str(payload.get("subject_scope") or "any"))
        if basis not in REAL_PERSON_BASES:
            # Owner grants cannot make fictional mode more restrictive than an explicit deny.
            return IdentityMediaAccessDecision(op, basis, runtime_ready, False, "direct-default", "fictional-direct" if runtime_ready else "runtime-pending", runtime_ready, record.version)
        granted = basis_allowed and subject_allowed and runtime_ready
        reason = "owner-grant" if granted else "owner-grant-scope-mismatch" if runtime_ready else "runtime-pending"
        return IdentityMediaAccessDecision(op, basis, granted, True, "owner-override", reason, runtime_ready, record.version, str(payload.get("subject_scope") or "any"))

    if basis == "fictional_inspired":
        return IdentityMediaAccessDecision(
            op,
            basis,
            runtime_ready,
            False,
            "direct-default",
            "fictional-direct" if runtime_ready else "runtime-pending",
            runtime_ready,
        )
    return IdentityMediaAccessDecision(op, basis, False, True, "owner-approval", "owner-approval-required", runtime_ready)


async def set_owner_access(
    session: AsyncSession,
    owner: UserRecord,
    *,
    user_id: str,
    operation: str,
    allowed: bool,
    identity_bases: list[str] | tuple[str, ...] | None = None,
    subject_scope: Literal["any", "exact"] = "any",
    subject_reference: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    _require_super_owner(owner)
    op = _operation(operation)
    user = await session.get(User, str(user_id or "").strip())
    if user is None or user.deleted_at is not None:
        raise ValueError("user-not-found")
    bases = list(dict.fromkeys(_basis(item) for item in (identity_bases or sorted(REAL_PERSON_BASES))))
    if not bases:
        raise ValueError("identity-bases-required")
    if any(item == "fictional_inspired" for item in bases):
        raise ValueError("fictional-mode-does-not-require-owner-grant")
    if subject_scope not in {"any", "exact"}:
        raise ValueError("invalid-subject-scope")
    subject = _subject(subject_reference, required=subject_scope == "exact")
    if len(note) > 1000:
        raise ValueError("owner-note-too-long")
    resource_id = _access_resource(user.id, op)
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == ACCESS_DOMAIN,
            OwnerControlRecord.resource_id == resource_id,
        )
        .with_for_update()
    )
    payload = {
        "user_id": user.id,
        "operation": op,
        "allowed": bool(allowed),
        "identity_bases": bases,
        "subject_scope": subject_scope,
        "subject_reference": subject if subject_scope == "exact" else None,
        "note": note.strip(),
        "updated_by": owner.id,
        "updated_at": _now().isoformat(),
    }
    if record is None:
        record = OwnerControlRecord(
            domain=ACCESS_DOMAIN,
            resource_id=resource_id,
            status="active",
            enabled=True,
            payload=payload,
            version=1,
        )
        session.add(record)
    else:
        record.status = "active"
        record.enabled = True
        record.payload = payload
        record.version += 1
    session.add(
        AuditEvent(
            organization_id=owner.organization_id,
            user_id=owner.id,
            action="identity_media.access.owner_updated",
            resource_type="identity_media_access",
            resource_id=resource_id,
            details={
                "target_user_id": user.id,
                "operation": op,
                "allowed": bool(allowed),
                "identity_bases": bases,
                "subject_scope": subject_scope,
                "subject_reference_present": subject is not None,
                "version": record.version,
            },
        )
    )
    await session.flush()
    return {
        "user_id": user.id,
        "user_email": user.email,
        "operation": op,
        "allowed": bool(allowed),
        "identity_bases": bases,
        "subject_scope": subject_scope,
        "subject_reference": subject if subject_scope == "exact" else None,
        "version": record.version,
    }


async def clear_owner_access(
    session: AsyncSession,
    owner: UserRecord,
    *,
    user_id: str,
    operation: str,
) -> bool:
    _require_super_owner(owner)
    op = _operation(operation)
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == ACCESS_DOMAIN,
            OwnerControlRecord.resource_id == _access_resource(user_id, op),
        )
        .with_for_update()
    )
    if record is None:
        return False
    record.status = "cleared"
    record.enabled = False
    record.version += 1
    payload = dict(record.payload or {})
    payload.update({"cleared_by": owner.id, "cleared_at": _now().isoformat()})
    record.payload = payload
    session.add(
        AuditEvent(
            organization_id=owner.organization_id,
            user_id=owner.id,
            action="identity_media.access.owner_cleared",
            resource_type="identity_media_access",
            resource_id=record.resource_id,
            details={"target_user_id": user_id, "operation": op, "version": record.version},
        )
    )
    await session.flush()
    return True


async def submit_access_request(
    session: AsyncSession,
    actor: UserRecord,
    *,
    operation: str,
    identity_basis: str,
    subject_reference: str,
    reason: str = "",
) -> dict[str, Any]:
    op = _operation(operation)
    basis = _basis(identity_basis)
    if basis not in REAL_PERSON_BASES:
        raise ValueError("fictional-mode-does-not-require-owner-approval")
    subject = _subject(subject_reference, required=True)
    if len(reason) > 1000:
        raise ValueError("request-reason-too-long")
    existing = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == REQUEST_DOMAIN,
            OwnerControlRecord.status == "active",
            OwnerControlRecord.enabled.is_(True),
            OwnerControlRecord.payload["user_id"].as_string() == actor.id,
            OwnerControlRecord.payload["operation"].as_string() == op,
            OwnerControlRecord.payload["identity_basis"].as_string() == basis,
            OwnerControlRecord.payload["subject_reference"].as_string() == subject,
            OwnerControlRecord.payload["review_status"].as_string() == "pending",
        )
    )
    if existing is not None:
        return _request_public(existing)
    request_id = str(uuid4())
    payload = {
        "request_id": request_id,
        "user_id": actor.id,
        "organization_id": actor.organization_id,
        "operation": op,
        "identity_basis": basis,
        "subject_reference": subject,
        "reason": reason.strip(),
        "review_status": "pending",
        "submitted_at": _now().isoformat(),
        "reviewed_at": None,
        "reviewed_by": None,
        "review_note": "",
    }
    record = OwnerControlRecord(
        domain=REQUEST_DOMAIN,
        resource_id=f"request:{request_id}",
        status="active",
        enabled=True,
        payload=payload,
        version=1,
    )
    session.add(record)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="identity_media.access.requested",
            resource_type="identity_media_access_request",
            resource_id=request_id,
            details={"operation": op, "identity_basis": basis, "subject_reference": subject},
        )
    )
    await session.flush()
    return _request_public(record)


def _request_public(record: OwnerControlRecord) -> dict[str, Any]:
    payload = dict(record.payload or {})
    return {
        "request_id": str(payload.get("request_id") or record.resource_id.removeprefix("request:")),
        "user_id": str(payload.get("user_id") or ""),
        "organization_id": str(payload.get("organization_id") or ""),
        "operation": str(payload.get("operation") or ""),
        "identity_basis": str(payload.get("identity_basis") or ""),
        "subject_reference": str(payload.get("subject_reference") or ""),
        "reason": str(payload.get("reason") or ""),
        "review_status": str(payload.get("review_status") or "pending"),
        "submitted_at": payload.get("submitted_at"),
        "reviewed_at": payload.get("reviewed_at"),
        "review_note": str(payload.get("review_note") or ""),
        "version": record.version,
    }


async def list_user_requests(session: AsyncSession, actor: UserRecord) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(
                    OwnerControlRecord.domain == REQUEST_DOMAIN,
                    OwnerControlRecord.enabled.is_(True),
                    OwnerControlRecord.payload["user_id"].as_string() == actor.id,
                )
                .order_by(OwnerControlRecord.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return [_request_public(row) for row in rows]


async def list_owner_requests(
    session: AsyncSession,
    owner: UserRecord,
    *,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    _require_super_owner(owner)
    statement = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == REQUEST_DOMAIN,
        OwnerControlRecord.enabled.is_(True),
    )
    if status:
        statement = statement.where(OwnerControlRecord.payload["review_status"].as_string() == status)
    rows = list((await session.scalars(statement.order_by(OwnerControlRecord.created_at.desc()).limit(limit))).all())
    user_ids = {str((row.payload or {}).get("user_id") or "") for row in rows}
    users = list((await session.scalars(select(User).where(User.id.in_(user_ids)))).all()) if user_ids else []
    by_id = {user.id: user for user in users}
    result = []
    for row in rows:
        item = _request_public(row)
        user = by_id.get(item["user_id"])
        item["user_email"] = user.email if user else ""
        item["user_name"] = user.name if user else ""
        result.append(item)
    return result


async def review_access_request(
    session: AsyncSession,
    owner: UserRecord,
    *,
    request_id: str,
    decision: Literal["approved", "denied", "revoked"],
    review_note: str = "",
) -> dict[str, Any]:
    _require_super_owner(owner)
    if decision not in {"approved", "denied", "revoked"}:
        raise ValueError("invalid-review-decision")
    if len(review_note) > 1000:
        raise ValueError("review-note-too-long")
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == REQUEST_DOMAIN,
            OwnerControlRecord.resource_id == f"request:{request_id}",
            OwnerControlRecord.enabled.is_(True),
        )
        .with_for_update()
    )
    if record is None:
        raise ValueError("access-request-not-found")
    payload = dict(record.payload or {})
    payload.update(
        {
            "review_status": decision,
            "reviewed_at": _now().isoformat(),
            "reviewed_by": owner.id,
            "review_note": review_note.strip(),
        }
    )
    record.payload = payload
    record.version += 1
    if decision == "approved":
        await set_owner_access(
            session,
            owner,
            user_id=str(payload.get("user_id") or ""),
            operation=str(payload.get("operation") or ""),
            allowed=True,
            identity_bases=[str(payload.get("identity_basis") or "")],
            subject_scope="exact",
            subject_reference=str(payload.get("subject_reference") or ""),
            note=f"Approved from request {request_id}. {review_note}".strip(),
        )
    elif decision == "revoked":
        await set_owner_access(
            session,
            owner,
            user_id=str(payload.get("user_id") or ""),
            operation=str(payload.get("operation") or ""),
            allowed=False,
            identity_bases=[str(payload.get("identity_basis") or "")],
            subject_scope="exact",
            subject_reference=str(payload.get("subject_reference") or ""),
            note=f"Revoked from request {request_id}. {review_note}".strip(),
        )
    session.add(
        AuditEvent(
            organization_id=owner.organization_id,
            user_id=owner.id,
            action="identity_media.access.request_reviewed",
            resource_type="identity_media_access_request",
            resource_id=request_id,
            details={"decision": decision, "target_user_id": payload.get("user_id"), "operation": payload.get("operation")},
        )
    )
    await session.flush()
    return _request_public(record)


async def list_owner_access(
    session: AsyncSession,
    owner: UserRecord,
    *,
    search: str = "",
    limit: int = 300,
) -> list[dict[str, Any]]:
    _require_super_owner(owner)
    statement = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == ACCESS_DOMAIN,
        OwnerControlRecord.status == "active",
        OwnerControlRecord.enabled.is_(True),
    )
    rows = list((await session.scalars(statement.order_by(OwnerControlRecord.updated_at.desc()).limit(limit))).all())
    user_ids = {str((row.payload or {}).get("user_id") or "") for row in rows}
    users = list((await session.scalars(select(User).where(User.id.in_(user_ids)))).all()) if user_ids else []
    by_id = {user.id: user for user in users}
    needle = search.strip().casefold()
    result: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row.payload or {})
        user = by_id.get(str(payload.get("user_id") or ""))
        if needle and not any(needle in value.casefold() for value in (str(payload.get("user_id") or ""), user.email if user else "", user.name if user else "")):
            continue
        result.append(
            {
                "user_id": str(payload.get("user_id") or ""),
                "user_email": user.email if user else "",
                "user_name": user.name if user else "",
                "operation": str(payload.get("operation") or ""),
                "allowed": bool(payload.get("allowed", True)),
                "identity_bases": list(payload.get("identity_bases") or []),
                "subject_scope": str(payload.get("subject_scope") or "any"),
                "subject_reference": payload.get("subject_reference"),
                "note": str(payload.get("note") or ""),
                "version": row.version,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )
    return result


async def search_users(
    session: AsyncSession,
    owner: UserRecord,
    *,
    query: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    _require_super_owner(owner)
    needle = str(query or "").strip()
    statement = select(User).where(User.deleted_at.is_(None))
    if needle:
        escaped = needle.replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        statement = statement.where(
            or_(User.email.ilike(pattern, escape="\\"), User.name.ilike(pattern, escape="\\"), User.id == needle)
        )
    rows = list((await session.scalars(statement.order_by(User.created_at.desc()).limit(limit))).all())
    return [
        {
            "id": row.id,
            "email": row.email,
            "name": row.name,
            "status": row.status,
            "organization_id": row.organization_id,
        }
        for row in rows
    ]


async def user_access_snapshot(
    session: AsyncSession,
    actor: UserRecord,
) -> dict[str, Any]:
    context = await billing.billing_context(session, actor.organization_id)
    account = context["account"]
    records = list(
        (
            await session.scalars(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == ACCESS_DOMAIN,
                    OwnerControlRecord.status == "active",
                    OwnerControlRecord.enabled.is_(True),
                    OwnerControlRecord.resource_id.like(f"user:{actor.id}:%"),
                )
            )
        ).all()
    )
    override_by_operation = {
        str((record.payload or {}).get("operation") or ""): record for record in records
    }
    operations: list[dict[str, Any]] = []
    for operation in OPERATIONS:
        runtime_ready = operation in RUNTIME_READY_OPERATIONS
        record = override_by_operation.get(operation)
        owner_override = None
        if record is not None:
            payload = dict(record.payload or {})
            owner_override = {
                "allowed": bool(payload.get("allowed", True)),
                "identity_bases": list(payload.get("identity_bases") or []),
                "subject_scope": str(payload.get("subject_scope") or "any"),
                "subject_reference": payload.get("subject_reference"),
                "version": record.version,
            }
        operations.append(
            {
                "operation": operation,
                "runtime_ready": runtime_ready,
                "fictional_inspired_direct": runtime_ready,
                "real_person_owner_approval_required": True,
                "licensed_public_figure_runtime_ready": False,
                "owner_override": owner_override,
            }
        )
    return {
        "schema": "identity-media-access.v1",
        "account_active": account.status in billing.ACTIVE_ACCOUNT_STATUSES,
        "operations": operations,
        "policy": {
            "fictional_inspired": "direct_when_runtime_ready",
            "real_person": "super_owner_approval_plus_rights_evidence",
            "licensed_public_figure": "super_owner_approval_plus_licensed_catalog_authority",
            "owner_grant_is_legal_license": False,
        },
    }
