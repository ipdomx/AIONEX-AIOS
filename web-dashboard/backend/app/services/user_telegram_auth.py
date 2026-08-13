"""Durable, user-scoped Telegram identity linking for the public AIOS bot.

A Telegram identity may only be linked with a short-lived, one-time challenge
issued to an already authenticated public-portal user.  Linked identities are
resolved against the current database user, role permissions, auth_version and
billing state on every command; Telegram never becomes an independent source of
authority.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, auth_service
from app.core.config import settings
from app.db.models import (
    AuditEvent,
    CommunicationEndpoint,
    ExternalIdentity,
    OwnerControlRecord,
    uuid_str,
)
from app.services import billing, communications

PROVIDER = "telegram_user_bot"
CHALLENGE_DOMAIN = "telegram-user-link-challenge"
BOT_IDENTITY_DOMAIN = "telegram-user-bot-identity"
CHALLENGE_TTL_SECONDS = 300
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 16


class UserTelegramAuthError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return _as_utc(parsed)


def _auth_version(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))


def _code_digest(code: str) -> str:
    normalized = code.strip().upper().encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), normalized, hashlib.sha256
    ).hexdigest()


async def _bot_identity(session: AsyncSession) -> dict[str, Any]:
    record = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == BOT_IDENTITY_DOMAIN,
            OwnerControlRecord.resource_id == "primary",
            OwnerControlRecord.enabled.is_(True),
            OwnerControlRecord.status == "active",
        )
    )
    return dict(record.payload or {}) if record is not None else {}


async def record_bot_identity(session: AsyncSession, payload: dict[str, Any]) -> None:
    safe_payload = {
        "telegram_bot_id": str(payload.get("id") or "")[:32],
        "username": str(payload.get("username") or "")[:128],
        "first_name": str(payload.get("first_name") or "AIONEX")[:160],
        "verified_at": _now().isoformat(),
    }
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == BOT_IDENTITY_DOMAIN,
            OwnerControlRecord.resource_id == "primary",
        )
        .with_for_update()
    )
    if record is None:
        record = OwnerControlRecord(
            domain=BOT_IDENTITY_DOMAIN,
            resource_id="primary",
            status="active",
            enabled=True,
            payload=safe_payload,
            version=1,
        )
        session.add(record)
    else:
        record.status = "active"
        record.enabled = True
        record.payload = safe_payload
        record.version += 1
    await session.flush()


async def issue_link_challenge(
    session: AsyncSession,
    actor: UserRecord,
) -> dict[str, Any]:
    if actor.role == "Super Owner":
        raise HTTPException(
            status_code=403, detail="Use the protected Owner Telegram bot"
        )
    code = _new_code()
    current = _now()
    expires_at = current + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    payload = {
        "user_id": actor.id,
        "organization_id": actor.organization_id,
        "auth_version": int(actor.auth_version),
        "code_digest": _code_digest(code),
        "issued_at": current.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == CHALLENGE_DOMAIN,
            OwnerControlRecord.resource_id == actor.id,
        )
        .with_for_update()
    )
    if record is None:
        record = OwnerControlRecord(
            domain=CHALLENGE_DOMAIN,
            resource_id=actor.id,
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
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="telegram.user_link.challenge_issued",
            resource_type="telegram_user_link",
            resource_id=actor.id,
            details={"expires_in_seconds": CHALLENGE_TTL_SECONDS},
        )
    )
    await session.flush()
    identity = await _bot_identity(session)
    username = str(identity.get("username") or "").lstrip("@")
    deep_link = f"https://t.me/{username}?start={code}" if username else None
    return {
        "code": code,
        "expires_at": expires_at.isoformat(),
        "expires_in_seconds": CHALLENGE_TTL_SECONDS,
        "bot_username": username or None,
        "deep_link": deep_link,
    }


async def status_snapshot(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.user_id == actor.id,
            ExternalIdentity.provider == PROVIDER,
        )
    )
    challenge = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == CHALLENGE_DOMAIN,
            OwnerControlRecord.resource_id == actor.id,
            OwnerControlRecord.enabled.is_(True),
            OwnerControlRecord.status == "active",
        )
    )
    challenge_expires_at = (
        _parse_datetime((challenge.payload or {}).get("expires_at"))
        if challenge is not None
        else None
    )
    current = _now()
    linked = identity is not None
    metadata = dict(identity.provider_metadata or {}) if identity is not None else {}
    bot_identity = await _bot_identity(session)
    username = str(bot_identity.get("username") or "").lstrip("@")
    return {
        "configured": bool(username and bot_identity.get("telegram_bot_id")),
        "linked": linked,
        "bot_username": username or None,
        "telegram_username": metadata.get("username") if linked else None,
        "linked_at": metadata.get("linked_at") if linked else None,
        "link_current": bool(
            linked
            and _auth_version(metadata.get("auth_version")) == int(actor.auth_version)
        ),
        "challenge_active": bool(
            challenge_expires_at and challenge_expires_at > current
        ),
        "challenge_expires_at": (
            challenge_expires_at.isoformat()
            if challenge_expires_at and challenge_expires_at > current
            else None
        ),
    }


async def _upsert_verified_endpoint(
    session: AsyncSession,
    actor: UserRecord,
    *,
    telegram_user_id: int,
    chat_id: int,
    username: str | None,
) -> CommunicationEndpoint:
    address = str(chat_id)
    digest = communications.address_hash(address)
    endpoints = list(
        (
            await session.scalars(
                select(CommunicationEndpoint).where(
                    CommunicationEndpoint.user_id == actor.id,
                    CommunicationEndpoint.channel == "telegram",
                    CommunicationEndpoint.status != "deleted",
                )
            )
        ).all()
    )
    endpoint = next((row for row in endpoints if row.address_hash == digest), None)
    for row in endpoints:
        if endpoint is not None and row.id == endpoint.id:
            continue
        row.status = "deleted"
    if endpoint is None:
        endpoint = CommunicationEndpoint(
            id=uuid_str(),
            organization_id=actor.organization_id,
            user_id=actor.id,
            channel="telegram",
            address_ciphertext=communications.encrypt_address(address),
            address_hash=digest,
            label="AIONEX User Telegram",
            status="active",
            verified_at=_now(),
            endpoint_metadata={},
        )
        session.add(endpoint)
    endpoint.organization_id = actor.organization_id
    endpoint.address_ciphertext = communications.encrypt_address(address)
    endpoint.status = "active"
    endpoint.verified_at = _now()
    endpoint.endpoint_metadata = {
        "masked_address": communications.mask_address(
            "telegram", str(telegram_user_id)
        ),
        "source": "verified_user_bot_link",
        "bot_scope": "user",
        "telegram_username": (username or "")[:128] or None,
    }
    await session.flush()
    return endpoint


async def consume_link_challenge(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    chat_id: int,
    code: str,
    username: str | None = None,
    display_name: str | None = None,
) -> UserRecord:
    if telegram_user_id <= 0 or chat_id <= 0:
        raise UserTelegramAuthError("invalid-telegram-identity")
    digest = _code_digest(code)
    records = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(
                    OwnerControlRecord.domain == CHALLENGE_DOMAIN,
                    OwnerControlRecord.enabled.is_(True),
                    OwnerControlRecord.status == "active",
                )
                .with_for_update()
            )
        ).all()
    )
    record: OwnerControlRecord | None = None
    for candidate in records:
        payload = dict(candidate.payload or {})
        if hmac.compare_digest(str(payload.get("code_digest") or ""), digest):
            record = candidate
            break
    if record is None:
        raise UserTelegramAuthError("invalid-link-code")
    payload = dict(record.payload or {})
    expires_at = _parse_datetime(payload.get("expires_at"))
    if expires_at is None or expires_at <= _now():
        record.status = "expired"
        record.enabled = False
        raise UserTelegramAuthError("expired-link-code")

    user_id = str(payload.get("user_id") or "")
    try:
        actor = await auth_service.get_user_by_id(session, user_id)
    except HTTPException as exc:
        raise UserTelegramAuthError("account-unavailable") from exc
    if actor.role == "Super Owner":
        raise UserTelegramAuthError("owner-bot-required")
    if _auth_version(payload.get("auth_version")) != int(actor.auth_version):
        raise UserTelegramAuthError("account-session-changed")

    by_telegram = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == PROVIDER,
            ExternalIdentity.subject == str(telegram_user_id),
        )
    )
    by_user = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == PROVIDER,
            ExternalIdentity.user_id == actor.id,
        )
    )
    if by_telegram is not None and by_telegram.user_id != actor.id:
        raise UserTelegramAuthError("telegram-already-linked")
    identity = by_user or by_telegram
    if identity is not None and identity.subject != str(telegram_user_id):
        raise UserTelegramAuthError("account-already-linked")
    metadata = {
        "chat_id": str(chat_id),
        "username": (username or "")[:128] or None,
        "display_name": (display_name or "")[:200] or None,
        "auth_version": int(actor.auth_version),
        "linked_at": _now().isoformat(),
        "verified_by": "portal_one_time_challenge",
        "private_chat_required": True,
    }
    if identity is None:
        identity = ExternalIdentity(
            user_id=actor.id,
            provider=PROVIDER,
            subject=str(telegram_user_id),
            email=actor.email,
            provider_metadata=metadata,
            last_login_at=_now(),
        )
        session.add(identity)
    else:
        identity.user_id = actor.id
        identity.subject = str(telegram_user_id)
        identity.email = actor.email
        identity.provider_metadata = metadata
        identity.last_login_at = _now()

    endpoint = await _upsert_verified_endpoint(
        session,
        actor,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        username=username,
    )
    record.status = "consumed"
    record.enabled = False
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="telegram.user_link.verified",
            resource_type="telegram_user_link",
            resource_id=identity.id,
            details={
                "telegram_user_hash": hashlib.sha256(
                    str(telegram_user_id).encode()
                ).hexdigest(),
                "verification": "portal_one_time_challenge",
                "endpoint_id": endpoint.id,
            },
        )
    )
    await session.flush()
    return actor


async def resolve_linked_user(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    chat_id: int,
) -> tuple[UserRecord, dict[str, Any]]:
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == PROVIDER,
            ExternalIdentity.subject == str(telegram_user_id),
        )
    )
    if identity is None:
        raise UserTelegramAuthError("not-linked")
    metadata = dict(identity.provider_metadata or {})
    if str(metadata.get("chat_id") or "") != str(chat_id):
        raise UserTelegramAuthError("chat-mismatch")
    try:
        actor = await auth_service.get_user_by_id(session, identity.user_id)
    except HTTPException as exc:
        raise UserTelegramAuthError("account-unavailable") from exc
    if actor.role == "Super Owner":
        raise UserTelegramAuthError("owner-bot-required")
    if _auth_version(metadata.get("auth_version")) != int(actor.auth_version):
        raise UserTelegramAuthError("relink-required")
    context = await billing.billing_context(session, actor.organization_id)
    account = context["account"]
    if account.status not in billing.ACTIVE_ACCOUNT_STATUSES:
        raise UserTelegramAuthError("billing-access-suspended")
    identity.last_login_at = _now()
    return actor, context


async def revoke_link(
    session: AsyncSession,
    actor: UserRecord,
) -> bool:
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == PROVIDER,
            ExternalIdentity.user_id == actor.id,
        )
    )
    changed = identity is not None
    if identity is not None:
        await session.delete(identity)
    endpoints = list(
        (
            await session.scalars(
                select(CommunicationEndpoint).where(
                    CommunicationEndpoint.user_id == actor.id,
                    CommunicationEndpoint.channel == "telegram",
                    CommunicationEndpoint.status != "deleted",
                )
            )
        ).all()
    )
    for endpoint in endpoints:
        if dict(endpoint.endpoint_metadata or {}).get("bot_scope") == "user":
            endpoint.status = "deleted"
            changed = True
    challenge = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == CHALLENGE_DOMAIN,
            OwnerControlRecord.resource_id == actor.id,
        )
    )
    if challenge is not None:
        challenge.status = "revoked"
        challenge.enabled = False
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="telegram.user_link.revoked",
            resource_type="telegram_user_link",
            resource_id=actor.id,
            details={"changed": changed},
        )
    )
    await session.flush()
    return changed


async def revoke_by_telegram(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    chat_id: int,
) -> UserRecord:
    actor, _context = await resolve_linked_user(
        session,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
    )
    await revoke_link(session, actor)
    return actor
