"""Durable Super Owner account bans and identity-match enforcement.

A ban is stronger than a session suspension: it revokes every existing session,
marks the account non-authenticatable, and records privacy-preserving hashes for
all durable identity signals AIOS already knows. Registration paths consult this
registry before creating a replacement account.

No web service can identify a person who presents an entirely new set of
unrelated identifiers. AIOS therefore fails closed on every known durable signal
without making probabilistic identity claims that could ban unrelated people.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    AuditEvent,
    ExternalIdentity,
    OwnerControlRecord,
    PasskeyCredential,
    RefreshSession,
    Role,
    User,
    uuid_str,
)

ACCOUNT_BAN_USER_DOMAIN = "account-ban-user"
ACCOUNT_BAN_EMAIL_DOMAIN = "account-ban-email"
ACCOUNT_BAN_USERNAME_DOMAIN = "account-ban-username"
ACCOUNT_BAN_PHONE_DOMAIN = "account-ban-phone"
ACCOUNT_BAN_FIREBASE_UID_DOMAIN = "account-ban-firebase-uid"
ACCOUNT_BAN_NETWORK_DOMAIN = "account-ban-network"
ACCOUNT_BAN_DEVICE_DOMAIN = "account-ban-device"
ACCOUNT_BAN_SOCIAL_DOMAIN = "account-ban-social"
ACCOUNT_BAN_PASSKEY_DOMAIN = "account-ban-passkey"
REGISTRATION_TELEMETRY_DOMAIN = "registration-telemetry"

BAN_DOMAINS = frozenset(
    {
        ACCOUNT_BAN_USER_DOMAIN,
        ACCOUNT_BAN_EMAIL_DOMAIN,
        ACCOUNT_BAN_USERNAME_DOMAIN,
        ACCOUNT_BAN_PHONE_DOMAIN,
        ACCOUNT_BAN_FIREBASE_UID_DOMAIN,
        ACCOUNT_BAN_NETWORK_DOMAIN,
        ACCOUNT_BAN_DEVICE_DOMAIN,
        ACCOUNT_BAN_SOCIAL_DOMAIN,
        ACCOUNT_BAN_PASSKEY_DOMAIN,
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


def identity_hmac(value: str) -> str:
    configured = os.getenv("AIOS_IDENTITY_HASH_SECRET")
    secret = (configured or settings.SECRET_KEY).encode("utf-8")
    if len(secret) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity protection secret is not configured",
        )
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _hashed(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    return identity_hmac(normalized) if normalized else None




def _merge_candidates(target: dict[str, str], source: dict[str, str]) -> None:
    """Preserve multiple independent signals that share one ban domain."""

    for domain, resource_id in source.items():
        if not resource_id:
            continue
        if domain not in target:
            target[domain] = resource_id
            continue
        if target[domain] == resource_id:
            continue
        target[f"{domain}:{resource_id}"] = resource_id

def _candidate_map(
    *,
    user_id: str | None = None,
    email: str | None = None,
    username: str | None = None,
    phone_hash: str | None = None,
    firebase_uid_hash: str | None = None,
    network_hash: str | None = None,
    device_hash: str | None = None,
    social_provider: str | None = None,
    social_subject: str | None = None,
    social_firebase_uid: str | None = None,
    passkey_credential_id: str | None = None,
) -> dict[str, str]:
    candidates: dict[str, str] = {}
    if user_id:
        candidates[ACCOUNT_BAN_USER_DOMAIN] = user_id
    email_hash = _hashed(email)
    if email_hash:
        candidates[ACCOUNT_BAN_EMAIL_DOMAIN] = email_hash
    username_hash = _hashed(username)
    if username_hash:
        candidates[ACCOUNT_BAN_USERNAME_DOMAIN] = username_hash
    if phone_hash:
        candidates[ACCOUNT_BAN_PHONE_DOMAIN] = phone_hash
    if firebase_uid_hash:
        candidates[ACCOUNT_BAN_FIREBASE_UID_DOMAIN] = firebase_uid_hash
    if network_hash:
        candidates[ACCOUNT_BAN_NETWORK_DOMAIN] = network_hash
    if device_hash:
        candidates[ACCOUNT_BAN_DEVICE_DOMAIN] = device_hash
    provider = str(social_provider or "").strip().lower()
    subject = str(social_subject or "").strip()
    if provider and subject:
        candidates[ACCOUNT_BAN_SOCIAL_DOMAIN] = identity_hmac(f"{provider}:{subject}")
    if social_firebase_uid:
        candidates[ACCOUNT_BAN_FIREBASE_UID_DOMAIN] = identity_hmac(
            str(social_firebase_uid).strip()
        )
    if passkey_credential_id:
        candidates[ACCOUNT_BAN_PASSKEY_DOMAIN] = identity_hmac(passkey_credential_id)
    return candidates


async def assert_registration_not_banned(
    session: AsyncSession,
    *,
    email: str | None = None,
    username: str | None = None,
    phone_hash: str | None = None,
    firebase_uid_hash: str | None = None,
    network_hash: str | None = None,
    device_hash: str | None = None,
    social_provider: str | None = None,
    social_subject: str | None = None,
    social_firebase_uid: str | None = None,
) -> None:
    candidates = _candidate_map(
        email=email,
        username=username,
        phone_hash=phone_hash,
        firebase_uid_hash=firebase_uid_hash,
        network_hash=network_hash,
        device_hash=device_hash,
        social_provider=social_provider,
        social_subject=social_subject,
        social_firebase_uid=social_firebase_uid,
    )
    if not candidates:
        return
    rows = list(
        (
            await session.scalars(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain.in_(tuple(candidates)),
                    OwnerControlRecord.enabled.is_(True),
                    OwnerControlRecord.status == "banned",
                )
            )
        ).all()
    )
    for row in rows:
        if candidates.get(row.domain) == row.resource_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ACCOUNT_BANNED",
                    "message": "This identity is not permitted to use AIONEX AIOS.",
                },
            )


async def assert_social_identity_not_banned(
    session: AsyncSession, identity: dict[str, Any]
) -> None:
    await assert_registration_not_banned(
        session,
        email=str(identity.get("email") or ""),
        social_provider=str(identity.get("provider") or ""),
        social_subject=str(identity.get("subject") or ""),
        social_firebase_uid=str(identity.get("firebase_uid") or ""),
    )


async def _known_user_candidates(
    session: AsyncSession, user: User
) -> dict[str, str]:
    candidates = _candidate_map(user_id=user.id, email=user.email)
    telemetry = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == REGISTRATION_TELEMETRY_DOMAIN,
            OwnerControlRecord.resource_id == user.id,
        )
    )
    if telemetry is not None:
        payload = dict(telemetry.payload or {})
        phone_verification = dict(payload.get("phone_verification") or {})
        _merge_candidates(
            candidates,
            _candidate_map(
                username=str(payload.get("username") or ""),
                phone_hash=str(payload.get("phone_hash") or "") or None,
                firebase_uid_hash=(
                    str(phone_verification.get("firebase_uid_hash") or "") or None
                ),
                network_hash=str(payload.get("network_hash") or "") or None,
                device_hash=str(payload.get("device_hash") or "") or None,
            ),
        )
    identities = list(
        (
            await session.scalars(
                select(ExternalIdentity).where(ExternalIdentity.user_id == user.id)
            )
        ).all()
    )
    for identity in identities:
        _merge_candidates(
            candidates,
            _candidate_map(
                email=identity.email,
                social_provider=identity.provider,
                social_subject=identity.subject,
                social_firebase_uid=str(
                    (identity.provider_metadata or {}).get("firebase_uid") or ""
                ),
            ),
        )
    passkeys = list(
        (
            await session.scalars(
                select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
            )
        ).all()
    )
    for passkey in passkeys:
        _merge_candidates(
            candidates,
            {ACCOUNT_BAN_PASSKEY_DOMAIN: identity_hmac(passkey.credential_id)},
        )
    return candidates


def _normalize_candidate_domains(candidates: dict[str, str]) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    for domain, resource_id in candidates.items():
        canonical = domain.split(":", 1)[0]
        normalized.append((canonical, resource_id))
    return list(dict.fromkeys(normalized))


async def _write_ban_record(
    session: AsyncSession,
    *,
    domain: str,
    resource_id: str,
    user_id: str,
    actor_id: str,
    reason: str,
) -> None:
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == domain,
            OwnerControlRecord.resource_id == resource_id,
        )
        .with_for_update()
    )
    current = dict(record.payload or {}) if record is not None else {}
    user_ids = {str(item) for item in current.get("user_ids", []) if item}
    legacy_user = str(current.get("user_id") or "")
    if (
        record is not None
        and record.enabled
        and record.status == "banned"
        and legacy_user
    ):
        user_ids.add(legacy_user)
    user_ids.add(user_id)
    reasons = dict(current.get("reasons") or {})
    reasons[user_id] = reason[:500]
    payload = {
        "user_id": sorted(user_ids)[0],
        "user_ids": sorted(user_ids),
        "banned_by": actor_id,
        "reason": reason[:500],
        "reasons": reasons,
        "banned_at": _now().isoformat(),
    }
    if record is None:
        session.add(
            OwnerControlRecord(
                id=uuid_str(),
                domain=domain,
                resource_id=resource_id,
                status="banned",
                enabled=True,
                payload=payload,
                version=1,
            )
        )
    else:
        record.status = "banned"
        record.enabled = True
        record.payload = payload
        record.version += 1


async def ban_user(
    session: AsyncSession,
    *,
    user: User,
    actor_id: str,
    reason: str = "Super Owner account ban",
) -> int:
    role = await session.get(Role, user.role_id) if user.role_id else None
    if user.id == actor_id or (role is not None and role.name == "Super Owner"):
        raise ValueError("The Super Owner account cannot be banned")
    candidates = _normalize_candidate_domains(await _known_user_candidates(session, user))
    for domain, resource_id in candidates:
        await _write_ban_record(
            session,
            domain=domain,
            resource_id=resource_id,
            user_id=user.id,
            actor_id=actor_id,
            reason=reason,
        )
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user.id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    user.status = "banned"
    user.auth_version += 1
    session.add(
        AuditEvent(
            organization_id=user.organization_id,
            user_id=actor_id,
            action="user.banned",
            resource_type="user",
            resource_id=user.id,
            details={"identity_signals": len(candidates), "reason": reason[:500]},
        )
    )
    return len(candidates)


async def unban_user(
    session: AsyncSession,
    *,
    user: User,
    actor_id: str,
) -> int:
    records = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(OwnerControlRecord.domain.in_(tuple(BAN_DOMAINS)))
                .with_for_update()
            )
        ).all()
    )
    changed = 0
    for record in records:
        payload = dict(record.payload or {})
        user_ids = {str(item) for item in payload.get("user_ids", []) if item}
        legacy_user = str(payload.get("user_id") or "")
        if record.enabled and record.status == "banned" and legacy_user:
            user_ids.add(legacy_user)
        if user.id not in user_ids:
            continue
        user_ids.discard(user.id)
        reasons = dict(payload.get("reasons") or {})
        reasons.pop(user.id, None)
        changed += 1
        if user_ids:
            payload["user_ids"] = sorted(user_ids)
            payload["user_id"] = sorted(user_ids)[0]
            payload["reasons"] = reasons
            record.payload = payload
            record.enabled = True
            record.status = "banned"
        else:
            record.enabled = False
            record.status = "revoked"
            payload["user_ids"] = []
            payload["reasons"] = {}
            record.payload = payload
        record.version += 1
    user.status = "active"
    user.auth_version += 1
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user.id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now())
    )
    session.add(
        AuditEvent(
            organization_id=user.organization_id,
            user_id=actor_id,
            action="user.ban_revoked",
            resource_type="user",
            resource_id=user.id,
            details={"identity_signals_released": changed},
        )
    )
    return changed
