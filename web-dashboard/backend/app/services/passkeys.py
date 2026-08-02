"""WebAuthn passkey ceremonies backed by PostgreSQL and one-use Redis state."""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from app.core.auth import UserRecord
from app.core.config import settings
from app.db.models import PasskeyCredential
from app.db.redis import get_redis
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

PASSKEY_CHALLENGE_PREFIX = "aionex:auth:passkey:ceremony:"


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    try:
        normalized = value.strip()
        if not normalized or len(normalized) > 2048:
            raise ValueError
        padding = "=" * (-len(normalized) % 4)
        decoded = base64.b64decode(
            normalized + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, UnicodeEncodeError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="Invalid passkey encoding") from exc
    if not decoded or len(decoded) > 1024:
        raise HTTPException(status_code=422, detail="Invalid passkey encoding")
    return decoded


def canonical_credential_id(value: str) -> str:
    return _b64url_encode(_b64url_decode(value))


def _credential_descriptor(row: PasskeyCredential) -> PublicKeyCredentialDescriptor:
    transports: list[AuthenticatorTransport] = []
    for value in row.transports:
        try:
            transports.append(AuthenticatorTransport(value))
        except ValueError:
            continue
    return PublicKeyCredentialDescriptor(
        id=_b64url_decode(row.credential_id),
        transports=transports or None,
    )


def _public_options(options: Any) -> dict[str, Any]:
    return json.loads(options_to_json(options))


async def _store_ceremony(
    ceremony_type: str,
    challenge: bytes,
    *,
    user_id: str | None = None,
) -> str:
    ceremony_id = secrets.token_urlsafe(32)
    payload = json.dumps(
        {
            "type": ceremony_type,
            "challenge": _b64url_encode(challenge),
            "user_id": user_id,
        },
        separators=(",", ":"),
    )
    try:
        redis = await get_redis()
        stored = await redis.set(
            f"{PASSKEY_CHALLENGE_PREFIX}{ceremony_id}",
            payload,
            ex=settings.PASSKEY_CHALLENGE_TTL_SECONDS,
            nx=True,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Passkey verification state is temporarily unavailable",
            headers={"Retry-After": "5"},
        ) from exc
    if not stored:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not create a passkey ceremony",
        )
    return ceremony_id


async def _consume_ceremony(
    ceremony_id: str,
    ceremony_type: str,
    *,
    user_id: str | None = None,
) -> bytes:
    if len(ceremony_id) < 20 or len(ceremony_id) > 256:
        raise HTTPException(status_code=422, detail="Invalid passkey ceremony")
    try:
        redis = await get_redis()
        raw = await redis.getdel(f"{PASSKEY_CHALLENGE_PREFIX}{ceremony_id}")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Passkey verification state is temporarily unavailable",
            headers={"Retry-After": "5"},
        ) from exc
    if not raw:
        raise HTTPException(
            status_code=410,
            detail="The passkey request expired or has already been used",
        )
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=410, detail="Invalid passkey ceremony") from exc
    if payload.get("type") != ceremony_type or payload.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Passkey ceremony does not match")
    return _b64url_decode(str(payload.get("challenge") or ""))


def passkey_public_configuration() -> dict[str, Any]:
    return {
        "enabled": settings.PASSKEY_ENABLED,
        "rp_id": settings.PASSKEY_RP_ID,
        "rp_name": settings.PASSKEY_RP_NAME,
        "timeout_ms": settings.PASSKEY_CHALLENGE_TTL_SECONDS * 1000,
    }


async def registration_options(
    session: AsyncSession,
    user: UserRecord,
) -> dict[str, Any]:
    _ensure_passkeys_enabled()
    existing = (
        (
            await session.execute(
                select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    options = generate_registration_options(
        rp_id=settings.PASSKEY_RP_ID,
        rp_name=settings.PASSKEY_RP_NAME,
        user_id=user.id.encode("utf-8"),
        user_name=user.email,
        user_display_name=user.name,
        timeout=settings.PASSKEY_CHALLENGE_TTL_SECONDS * 1000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            authenticator_attachment=AuthenticatorAttachment.PLATFORM,
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[_credential_descriptor(row) for row in existing],
    )
    ceremony_id = await _store_ceremony(
        "registration", options.challenge, user_id=user.id
    )
    return {"ceremony_id": ceremony_id, "public_key": _public_options(options)}


async def verify_registration(
    session: AsyncSession,
    user: UserRecord,
    *,
    ceremony_id: str,
    credential: dict[str, Any],
    nickname: str,
) -> PasskeyCredential:
    _ensure_passkeys_enabled()
    challenge = await _consume_ceremony(ceremony_id, "registration", user_id=user.id)
    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.PASSKEY_RP_ID,
            expected_origin=settings.PASSKEY_ALLOWED_ORIGINS,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422, detail="Passkey registration verification failed"
        ) from exc

    credential_id = _b64url_encode(verification.credential_id)
    if len(credential_id) > 1024:
        raise HTTPException(status_code=422, detail="Passkey credential is too large")
    existing = await session.scalar(
        select(PasskeyCredential).where(
            PasskeyCredential.credential_id == credential_id
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="This passkey is already registered"
        )
    response = credential.get("response")
    transports = response.get("transports", []) if isinstance(response, dict) else []
    allowed_transports = {
        "ble",
        "cable",
        "hybrid",
        "internal",
        "nfc",
        "smart-card",
        "usb",
    }
    row = PasskeyCredential(
        user_id=user.id,
        credential_id=credential_id,
        public_key=_b64url_encode(verification.credential_public_key),
        sign_count=verification.sign_count,
        transports=[
            value
            for value in transports
            if isinstance(value, str) and value in allowed_transports
        ],
        aaguid=str(verification.aaguid) if verification.aaguid else None,
        device_type=getattr(verification.credential_device_type, "value", None),
        backed_up=bool(verification.credential_backed_up),
        nickname=nickname.strip() or "Passkey",
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="This passkey is already registered",
        ) from exc
    await session.refresh(row)
    return row


async def authentication_options() -> dict[str, Any]:
    _ensure_passkeys_enabled()
    options = generate_authentication_options(
        rp_id=settings.PASSKEY_RP_ID,
        timeout=settings.PASSKEY_CHALLENGE_TTL_SECONDS * 1000,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    ceremony_id = await _store_ceremony("authentication", options.challenge)
    return {"ceremony_id": ceremony_id, "public_key": _public_options(options)}


async def verify_authentication(
    session: AsyncSession,
    *,
    ceremony_id: str,
    credential: dict[str, Any],
) -> PasskeyCredential:
    _ensure_passkeys_enabled()
    challenge = await _consume_ceremony(ceremony_id, "authentication")
    raw_id = str(credential.get("rawId") or credential.get("id") or "")
    credential_id = canonical_credential_id(raw_id)
    row = await session.scalar(
        select(PasskeyCredential)
        .where(PasskeyCredential.credential_id == credential_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=401, detail="Passkey is not registered")
    response = credential.get("response")
    user_handle = response.get("userHandle") if isinstance(response, dict) else None
    if user_handle is not None:
        if not isinstance(user_handle, str) or _b64url_decode(
            user_handle
        ) != row.user_id.encode("utf-8"):
            raise HTTPException(status_code=401, detail="Passkey user does not match")
    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=settings.PASSKEY_RP_ID,
            expected_origin=settings.PASSKEY_ALLOWED_ORIGINS,
            credential_public_key=_b64url_decode(row.public_key),
            credential_current_sign_count=row.sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=401, detail="Passkey authentication verification failed"
        ) from exc
    row.sign_count = verification.new_sign_count
    row.device_type = getattr(verification.credential_device_type, "value", None)
    row.backed_up = bool(verification.credential_backed_up)
    row.last_used_at = datetime.now(UTC)
    await session.flush()
    return row


def _ensure_passkeys_enabled() -> None:
    if not settings.PASSKEY_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Passkey authentication is disabled",
        )


def serialize_passkey(row: PasskeyCredential) -> dict[str, Any]:
    return {
        "id": row.id,
        "nickname": row.nickname,
        "transports": row.transports,
        "device_type": row.device_type,
        "backed_up": row.backed_up,
        "created_at": row.created_at.isoformat(),
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
    }
