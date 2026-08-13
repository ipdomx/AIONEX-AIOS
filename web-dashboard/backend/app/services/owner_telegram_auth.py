"""Strong second-factor authentication for the private Super Owner Telegram bot.

The Telegram allowlist and private-chat check remain the first boundary. Operational
commands additionally require a short-lived authenticated Telegram session created
with a one-time code that can only be issued from the protected Owner Control plane.
Only HMAC digests of one-time codes are persisted.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.core.config import settings
from app.db.models import AuditEvent, OwnerControlRecord, Role, User, uuid_str

CHALLENGE_DOMAIN = "telegram-owner-auth-challenge"
SESSION_DOMAIN = "telegram-owner-auth-session"
FAILURE_DOMAIN = "telegram-owner-auth-failure"

CHALLENGE_TTL_SECONDS = 300
SESSION_TTL_SECONDS = 1800
MAX_FAILURES = 5
LOCKOUT_SECONDS = 900


class TelegramOwnerAuthError(RuntimeError):
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


def _code_digest(code: str) -> str:
    secret = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(secret, code.encode("utf-8"), hashlib.sha256).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(10_000_000_000):010d}"


async def _owner_is_current(
    session: AsyncSession,
    *,
    owner_user_id: str,
    auth_version: int,
) -> bool:
    user = await session.get(User, owner_user_id)
    if (
        user is None
        or user.deleted_at is not None
        or user.status not in {"active", "online"}
        or int(user.auth_version) != int(auth_version)
        or user.role_id is None
    ):
        return False
    role = await session.get(Role, user.role_id)
    return role is not None and role.status == "active" and role.name == "Super Owner"


async def issue_challenge(
    session: AsyncSession,
    actor: UserRecord,
) -> dict[str, Any]:
    """Issue exactly one active one-time code for the authenticated Super Owner."""

    current = _now()
    code = _new_code()
    expires_at = current + timedelta(seconds=CHALLENGE_TTL_SECONDS)
    payload = {
        "owner_user_id": actor.id,
        "owner_auth_version": int(actor.auth_version),
        "code_digest": _code_digest(code),
        "expires_at": expires_at.isoformat(),
        "issued_at": current.isoformat(),
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
            id=uuid_str(),
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
            action="telegram.owner_auth.challenge_issued",
            resource_type="owner_telegram_auth",
            resource_id=actor.id,
            details={"expires_in_seconds": CHALLENGE_TTL_SECONDS},
        )
    )
    await session.flush()
    return {
        "code": code,
        "expires_at": expires_at.isoformat(),
        "expires_in_seconds": CHALLENGE_TTL_SECONDS,
    }


async def security_snapshot(session: AsyncSession, actor: UserRecord) -> dict[str, Any]:
    current = _now()
    sessions = list(
        (
            await session.scalars(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == SESSION_DOMAIN,
                    OwnerControlRecord.enabled.is_(True),
                    OwnerControlRecord.status == "active",
                )
            )
        ).all()
    )
    active_session: OwnerControlRecord | None = None
    for record in sessions:
        payload = dict(record.payload or {})
        if str(payload.get("owner_user_id") or "") != actor.id:
            continue
        expires_at = _parse_datetime(payload.get("expires_at"))
        if expires_at and expires_at > current:
            active_session = record
            break

    challenges = list(
        (
            await session.scalars(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == CHALLENGE_DOMAIN,
                    OwnerControlRecord.enabled.is_(True),
                    OwnerControlRecord.status == "active",
                )
            )
        ).all()
    )
    challenge_expires_at: datetime | None = None
    for record in challenges:
        payload = dict(record.payload or {})
        if str(payload.get("owner_user_id") or "") != actor.id:
            continue
        expires_at = _parse_datetime(payload.get("expires_at"))
        if expires_at and expires_at > current:
            challenge_expires_at = expires_at
            break

    session_expires_at = (
        _parse_datetime((active_session.payload or {}).get("expires_at"))
        if active_session is not None
        else None
    )
    return {
        "auth_required": True,
        "private_chat_required": True,
        "allowlist_required": True,
        "challenge_ttl_seconds": CHALLENGE_TTL_SECONDS,
        "session_ttl_seconds": SESSION_TTL_SECONDS,
        "max_failures": MAX_FAILURES,
        "lockout_seconds": LOCKOUT_SECONDS,
        "challenge_active": challenge_expires_at is not None,
        "challenge_expires_at": (
            challenge_expires_at.isoformat() if challenge_expires_at else None
        ),
        "session_active": session_expires_at is not None,
        "session_expires_at": session_expires_at.isoformat() if session_expires_at else None,
    }


async def _failure_state(
    session: AsyncSession, telegram_user_id: int
) -> OwnerControlRecord | None:
    return await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == FAILURE_DOMAIN,
            OwnerControlRecord.resource_id == str(telegram_user_id),
        )
        .with_for_update()
    )


async def _record_failure(session: AsyncSession, telegram_user_id: int) -> None:
    current = _now()
    record = await _failure_state(session, telegram_user_id)
    payload = dict(record.payload or {}) if record is not None else {}
    lockout_until = _parse_datetime(payload.get("lockout_until"))
    failures = int(payload.get("failures") or 0)
    if lockout_until is None or lockout_until <= current:
        if lockout_until is not None:
            failures = 0
        lockout_until = None
    failures += 1
    if failures >= MAX_FAILURES:
        lockout_until = current + timedelta(seconds=LOCKOUT_SECONDS)
        failures = MAX_FAILURES
    new_payload = {
        "failures": failures,
        "lockout_until": lockout_until.isoformat() if lockout_until else None,
        "updated_at": current.isoformat(),
    }
    if record is None:
        session.add(
            OwnerControlRecord(
                id=uuid_str(),
                domain=FAILURE_DOMAIN,
                resource_id=str(telegram_user_id),
                status="locked" if lockout_until else "active",
                enabled=True,
                payload=new_payload,
                version=1,
            )
        )
    else:
        record.status = "locked" if lockout_until else "active"
        record.enabled = True
        record.payload = new_payload
        record.version += 1


async def _ensure_not_locked(session: AsyncSession, telegram_user_id: int) -> None:
    current = _now()
    record = await _failure_state(session, telegram_user_id)
    if record is None:
        return
    lockout_until = _parse_datetime((record.payload or {}).get("lockout_until"))
    if lockout_until and lockout_until > current:
        raise TelegramOwnerAuthError("locked")


async def authenticate(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    chat_id: int,
    code: str,
) -> dict[str, Any]:
    await _ensure_not_locked(session, telegram_user_id)
    current = _now()
    supplied = _code_digest(code.strip())
    candidates = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(
                    OwnerControlRecord.domain == CHALLENGE_DOMAIN,
                    OwnerControlRecord.enabled.is_(True),
                    OwnerControlRecord.status == "active",
                )
                .order_by(OwnerControlRecord.created_at.desc())
                .with_for_update()
            )
        ).all()
    )
    matched: OwnerControlRecord | None = None
    owner_user_id = ""
    owner_auth_version = -1
    for record in candidates:
        payload = dict(record.payload or {})
        expires_at = _parse_datetime(payload.get("expires_at"))
        if expires_at is None or expires_at <= current:
            record.enabled = False
            record.status = "expired"
            record.version += 1
            continue
        expected = str(payload.get("code_digest") or "")
        if expected and hmac.compare_digest(expected, supplied):
            owner_user_id = str(payload.get("owner_user_id") or "")
            owner_auth_version = int(payload.get("owner_auth_version") or 0)
            if await _owner_is_current(
                session,
                owner_user_id=owner_user_id,
                auth_version=owner_auth_version,
            ):
                matched = record
                break

    if matched is None:
        await _record_failure(session, telegram_user_id)
        session.add(
            AuditEvent(
                organization_id=None,
                user_id=None,
                action="telegram.owner_auth.failed",
                resource_type="owner_telegram_auth",
                resource_id=None,
                details={"reason": "invalid_or_expired_code"},
            )
        )
        await session.flush()
        raise TelegramOwnerAuthError("invalid_code")

    matched.enabled = False
    matched.status = "consumed"
    matched.payload = {
        key: value
        for key, value in dict(matched.payload or {}).items()
        if key != "code_digest"
    } | {"consumed_at": current.isoformat()}
    matched.version += 1

    expires_at = current + timedelta(seconds=SESSION_TTL_SECONDS)
    auth_session = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == SESSION_DOMAIN,
            OwnerControlRecord.resource_id == str(telegram_user_id),
        )
        .with_for_update()
    )
    payload = {
        "owner_user_id": owner_user_id,
        "owner_auth_version": owner_auth_version,
        "chat_id": str(chat_id),
        "authenticated_at": current.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    if auth_session is None:
        auth_session = OwnerControlRecord(
            id=uuid_str(),
            domain=SESSION_DOMAIN,
            resource_id=str(telegram_user_id),
            status="active",
            enabled=True,
            payload=payload,
            version=1,
        )
        session.add(auth_session)
    else:
        auth_session.status = "active"
        auth_session.enabled = True
        auth_session.payload = payload
        auth_session.version += 1

    failure = await _failure_state(session, telegram_user_id)
    if failure is not None:
        failure.status = "cleared"
        failure.enabled = False
        failure.payload = {"failures": 0, "lockout_until": None}
        failure.version += 1

    owner = await session.get(User, owner_user_id)
    session.add(
        AuditEvent(
            organization_id=owner.organization_id if owner else None,
            user_id=owner_user_id or None,
            action="telegram.owner_auth.authenticated",
            resource_type="owner_telegram_auth",
            resource_id=auth_session.resource_id,
            details={"expires_in_seconds": SESSION_TTL_SECONDS},
        )
    )
    await session.flush()
    return {"expires_at": expires_at.isoformat(), "expires_in_seconds": SESSION_TTL_SECONDS}


async def require_active_session(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    chat_id: int,
) -> str:
    record = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == SESSION_DOMAIN,
            OwnerControlRecord.resource_id == str(telegram_user_id),
            OwnerControlRecord.enabled.is_(True),
            OwnerControlRecord.status == "active",
        )
    )
    if record is None:
        raise TelegramOwnerAuthError("session_required")
    payload = dict(record.payload or {})
    if str(payload.get("chat_id") or "") != str(chat_id):
        raise TelegramOwnerAuthError("session_required")
    expires_at = _parse_datetime(payload.get("expires_at"))
    if expires_at is None or expires_at <= _now():
        raise TelegramOwnerAuthError("session_expired")
    owner_user_id = str(payload.get("owner_user_id") or "")
    owner_auth_version = int(payload.get("owner_auth_version") or 0)
    if not await _owner_is_current(
        session,
        owner_user_id=owner_user_id,
        auth_version=owner_auth_version,
    ):
        raise TelegramOwnerAuthError("session_invalidated")
    return owner_user_id


async def revoke_telegram_session(
    session: AsyncSession,
    *,
    telegram_user_id: int,
    owner_user_id: str | None = None,
) -> bool:
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == SESSION_DOMAIN,
            OwnerControlRecord.resource_id == str(telegram_user_id),
        )
        .with_for_update()
    )
    if record is None:
        return False
    payload = dict(record.payload or {})
    if owner_user_id and str(payload.get("owner_user_id") or "") != owner_user_id:
        return False
    record.enabled = False
    record.status = "revoked"
    record.payload = payload | {"revoked_at": _now().isoformat()}
    record.version += 1
    return True


async def revoke_owner_sessions(session: AsyncSession, actor: UserRecord) -> int:
    records = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(
                    OwnerControlRecord.domain == SESSION_DOMAIN,
                    OwnerControlRecord.enabled.is_(True),
                    OwnerControlRecord.status == "active",
                )
                .with_for_update()
            )
        ).all()
    )
    changed = 0
    for record in records:
        if str((record.payload or {}).get("owner_user_id") or "") != actor.id:
            continue
        record.enabled = False
        record.status = "revoked"
        record.payload = dict(record.payload or {}) | {"revoked_at": _now().isoformat()}
        record.version += 1
        changed += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="telegram.owner_auth.sessions_revoked",
            resource_type="owner_telegram_auth",
            resource_id=actor.id,
            details={"sessions_revoked": changed},
        )
    )
    await session.flush()
    return changed
