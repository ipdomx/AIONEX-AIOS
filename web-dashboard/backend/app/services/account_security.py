"""Password recovery and TOTP multi-factor authentication services."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import secrets
import smtplib
import struct
import time
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import quote

import jwt
from app.core.auth import UserRecord, auth_service, pwd_context
from app.core.config import settings
from app.db.models import (
    AuditEvent,
    PasswordResetToken,
    RefreshSession,
    User,
    UserMFA,
    uuid_str,
)
from app.db.redis import get_redis
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request, status
from jwt import InvalidTokenError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

_RESET_RESPONSE = {
    "message": "If the account exists, password recovery instructions will be sent."
}
_MFA_CHALLENGE_SECONDS = 300
_MFA_REPLAY_PREFIX = "aionex:auth:mfa:used:"
_RESET_RATE_PREFIX = "aionex:auth:password-reset:"


def _now() -> datetime:
    return datetime.now(UTC)


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt_secret(secret: str) -> str:
    return _fernet().encrypt(secret.encode("ascii")).decode("ascii")


def _decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=503, detail="MFA secret cannot be decrypted") from exc


def _backup_hash(user_id: str, code: str) -> str:
    normalized = code.replace("-", "").replace(" ", "").upper()
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"{user_id}:{normalized}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _totp(secret: str, counter: int | None = None) -> str:
    step = int(time.time() // 30) if counter is None else counter
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def verify_totp(secret: str, code: str, *, window: int = 1) -> bool:
    normalized = code.strip().replace(" ", "")
    if len(normalized) != 6 or not normalized.isdigit():
        return False
    counter = int(time.time() // 30)
    return any(hmac.compare_digest(_totp(secret, counter + offset), normalized) for offset in range(-window, window + 1))


async def _rate_limit_password_reset(email: str, request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    key = f"{_RESET_RATE_PREFIX}{hashlib.sha256(f'{email}:{ip}'.encode()).hexdigest()}"
    try:
        redis = await get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 900)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Password recovery is temporarily unavailable",
        ) from exc
    if count > 5:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many password recovery requests",
            headers={"Retry-After": "900"},
        )


def _deliver_password_reset(email: str, raw_token: str) -> None:
    if not settings.SMTP_HOST:
        raise RuntimeError("smtp-unconfigured")
    reset_url = f"{settings.PASSWORD_RESET_URL_BASE}?token={quote(raw_token, safe='')}"
    message = EmailMessage()
    message["Subject"] = "Reset your AIONEX AIOS password"
    message["From"] = settings.SMTP_USER or "noreply@aionex.local"
    message["To"] = email
    message.set_content(
        "A password reset was requested for your AIONEX AIOS account.\n\n"
        f"Open this link within {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes:\n"
        f"{reset_url}\n\n"
        "If you did not request this, no action is required."
    )
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        smtp.ehlo()
        if settings.SMTP_TLS:
            smtp.starttls()
            smtp.ehlo()
        if settings.SMTP_USER:
            if not settings.SMTP_PASSWORD:
                raise RuntimeError("smtp-password-unconfigured")
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        refused = smtp.send_message(message)
    if refused:
        raise RuntimeError("smtp-recipient-refused")


async def request_password_reset(
    session: AsyncSession,
    request: Request,
    email: str,
) -> dict[str, str]:
    normalized = email.strip().lower()
    await _rate_limit_password_reset(normalized, request)
    user = await session.scalar(
        select(User).where(
            User.email == normalized,
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        return dict(_RESET_RESPONSE)

    now = _now()
    await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now, updated_at=now)
    )
    raw_token = secrets.token_urlsafe(48)
    record = PasswordResetToken(
        id=uuid_str(),
        user_id=user.id,
        token_hash=_token_hash(raw_token),
        expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        requested_ip=request.client.host if request.client else None,
        delivery_status="pending",
    )
    session.add(record)
    session.add(
        AuditEvent(
            organization_id=user.organization_id,
            user_id=user.id,
            action="auth.password_reset_requested",
            resource_type="password_reset",
            resource_id=record.id,
            details={"delivery": "pending"},
            ip_address=request.client.host if request.client else None,
        )
    )
    await session.commit()

    try:
        await asyncio.to_thread(_deliver_password_reset, user.email, raw_token)
        record.delivery_status = "sent"
    except Exception as exc:
        record.delivery_status = (
            "unconfigured" if str(exc) in {"smtp-unconfigured", "smtp-password-unconfigured"} else "failed"
        )
    record.delivery_attempted_at = _now()
    await session.commit()
    return dict(_RESET_RESPONSE)


async def confirm_password_reset(
    session: AsyncSession,
    request: Request,
    raw_token: str,
    new_password: str,
) -> dict[str, str]:
    if len(new_password) < settings.PASSWORD_MIN_LENGTH:
        raise HTTPException(
            status_code=422,
            detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters",
        )
    record = await session.scalar(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == _token_hash(raw_token))
        .with_for_update()
    )
    now = _now()
    if record is None or record.used_at is not None or record.expires_at <= now:
        raise HTTPException(status_code=400, detail="Password reset token is invalid or expired")
    user = await session.get(User, record.user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Password reset token is invalid or expired")
    if pwd_context.verify(new_password, user.password_hash):
        raise HTTPException(status_code=409, detail="New password must differ from the current password")

    user.password_hash = pwd_context.hash(new_password)
    user.auth_version += 1
    record.used_at = now
    await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now, updated_at=now)
    )
    await session.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user.id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    session.add(
        AuditEvent(
            organization_id=user.organization_id,
            user_id=user.id,
            action="auth.password_reset_completed",
            resource_type="user",
            resource_id=user.id,
            details={"sessions_revoked": True},
            ip_address=request.client.host if request.client else None,
        )
    )
    await session.commit()
    return {"message": "Password reset completed successfully"}


async def mfa_enabled(session: AsyncSession, user_id: str) -> bool:
    record = await session.get(UserMFA, user_id)
    return bool(record and record.enabled)


async def mfa_status(session: AsyncSession, user_id: str) -> dict[str, object]:
    record = await session.get(UserMFA, user_id)
    return {
        "enabled": bool(record and record.enabled),
        "backup_codes_remaining": len(record.backup_code_hashes) if record and record.enabled else 0,
        "verified_at": record.verified_at.isoformat() if record and record.verified_at else None,
    }


async def start_mfa_setup(session: AsyncSession, user: UserRecord) -> dict[str, object]:
    existing = await session.get(UserMFA, user.id)
    if existing is not None and existing.enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled")
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    backup_codes = [f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}" for _ in range(8)]
    if existing is None:
        existing = UserMFA(user_id=user.id, secret_ciphertext="", backup_code_hashes=[])
        session.add(existing)
    existing.secret_ciphertext = _encrypt_secret(secret)
    existing.backup_code_hashes = [_backup_hash(user.id, code) for code in backup_codes]
    existing.enabled = False
    existing.verified_at = None
    await session.commit()
    label = quote(user.email, safe="")
    issuer = quote("AIONEX AIOS", safe="")
    uri = f"otpauth://totp/{issuer}:{label}?secret={secret}&issuer={issuer}&digits=6&period=30"
    return {"secret": secret, "qr_code": uri, "backup_codes": backup_codes}


async def _verify_mfa_code(session: AsyncSession, user_id: str, code: str, *, consume_backup: bool) -> bool:
    record = await session.get(UserMFA, user_id)
    if record is None:
        return False
    secret = _decrypt_secret(record.secret_ciphertext)
    if verify_totp(secret, code):
        record.last_used_at = _now()
        return True
    candidate = _backup_hash(user_id, code)
    if candidate in record.backup_code_hashes:
        if consume_backup:
            record.backup_code_hashes = [value for value in record.backup_code_hashes if value != candidate]
        record.last_used_at = _now()
        return True
    return False


async def confirm_mfa_setup(session: AsyncSession, user: UserRecord, code: str) -> dict[str, object]:
    record = await session.get(UserMFA, user.id)
    if record is None:
        raise HTTPException(status_code=409, detail="MFA setup has not been started")
    secret = _decrypt_secret(record.secret_ciphertext)
    if not verify_totp(secret, code):
        raise HTTPException(status_code=400, detail="Invalid MFA code")
    record.last_used_at = _now()
    record.enabled = True
    record.verified_at = _now()
    await session.commit()
    return await mfa_status(session, user.id)


async def disable_mfa(
    session: AsyncSession,
    user: UserRecord,
    current_password: str,
    code: str,
) -> dict[str, object]:
    db_user = await session.get(User, user.id)
    if db_user is None or not pwd_context.verify(current_password, db_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    record = await session.get(UserMFA, user.id)
    if record is None or not record.enabled:
        raise HTTPException(status_code=409, detail="MFA is not enabled")
    if not await _verify_mfa_code(session, user.id, code, consume_backup=True):
        raise HTTPException(status_code=400, detail="Invalid MFA code")
    await session.delete(record)
    db_user.auth_version += 1
    await session.execute(
        update(RefreshSession)
        .where(RefreshSession.user_id == user.id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=_now())
    )
    await session.commit()
    return {"enabled": False, "backup_codes_remaining": 0, "verified_at": None}


def create_mfa_challenge(user: UserRecord) -> dict[str, object]:
    now = _now()
    payload = {
        "sub": user.id,
        "auth_version": user.auth_version,
        "type": "mfa_challenge",
        "jti": secrets.token_urlsafe(18),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=_MFA_CHALLENGE_SECONDS)).timestamp()),
    }
    return {
        "mfa_required": True,
        "challenge_token": jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM),
        "expires_in": _MFA_CHALLENGE_SECONDS,
    }


async def consume_mfa_challenge(
    session: AsyncSession,
    challenge_token: str,
    code: str,
) -> UserRecord:
    try:
        payload = jwt.decode(challenge_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="MFA challenge is invalid or expired") from exc
    if payload.get("type") != "mfa_challenge" or not payload.get("sub") or not payload.get("jti"):
        raise HTTPException(status_code=401, detail="MFA challenge is invalid or expired")
    user = await auth_service.get_user_by_id(session, str(payload["sub"]))
    if int(payload.get("auth_version", -1)) != user.auth_version:
        raise HTTPException(status_code=401, detail="MFA challenge is no longer valid")
    record = await session.get(UserMFA, user.id)
    if record is None or not record.enabled:
        raise HTTPException(status_code=401, detail="MFA challenge is no longer valid")
    if not await _verify_mfa_code(session, user.id, code, consume_backup=True):
        raise HTTPException(status_code=401, detail="Invalid MFA code")
    try:
        redis = await get_redis()
        accepted = await redis.set(
            f"{_MFA_REPLAY_PREFIX}{payload['jti']}",
            "1",
            ex=_MFA_CHALLENGE_SECONDS,
            nx=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="MFA state is temporarily unavailable") from exc
    if not accepted:
        raise HTTPException(status_code=401, detail="MFA challenge has already been used")
    await session.commit()
    return user
