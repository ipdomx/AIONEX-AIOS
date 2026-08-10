"""Social OAuth/OIDC exchange and device-bound WebAuthn passkey endpoints."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from app.core.auth import (
    UserRecord,
    attach_browser_session_cookies,
    auth_service,
    current_user,
    enforce_auth_channel_role,
)
from app.db.base import get_db
from app.db.models import (
    AuditEvent,
    ExternalIdentity,
    PasskeyCredential,
    RefreshSession,
    User,
)
from app.services.firebase_social import (
    create_social_registration,
    firebase_social_public_configuration,
    verify_firebase_social_id_token,
)
from app.services.free_tier import client_ip_from_request
from app.services.passkeys import (
    authentication_options,
    passkey_public_configuration,
    registration_options,
    serialize_passkey,
    verify_authentication,
    verify_registration,
)
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class SessionResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class FirebaseSocialSessionRequest(BaseModel):
    id_token: str = Field(min_length=100, max_length=8192)


class SocialRegistrationPreparationResponse(BaseModel):
    registration_token: str
    provider: str
    email: str
    name: str | None = None
    expires_in: int


class PasskeyRegistrationVerifyRequest(BaseModel):
    ceremony_id: str = Field(min_length=20, max_length=256)
    credential: dict[str, Any]
    nickname: str = Field(default="Passkey", min_length=1, max_length=120)


class PasskeyAuthenticationVerifyRequest(BaseModel):
    ceremony_id: str = Field(min_length=20, max_length=256)
    credential: dict[str, Any]


async def _audit_session(
    session: AsyncSession,
    request: Request,
    response: dict[str, Any],
    user: UserRecord,
    *,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    refresh_hash = hashlib.sha256(
        str(response["refresh_token"]).encode("utf-8")
    ).hexdigest()
    refresh_session = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == refresh_hash)
    )
    ip_address = client_ip_from_request(request)
    if refresh_session is not None:
        refresh_session.ip_address = ip_address
        refresh_session.user_agent = (request.headers.get("user-agent") or "")[:2000]
    session.add(
        AuditEvent(
            organization_id=user.organization_id,
            user_id=user.id,
            action=action,
            resource_type="session",
            resource_id=refresh_session.id if refresh_session else None,
            details={
                "country": request.headers.get("cf-ipcountry"),
                **(details or {}),
            },
            ip_address=ip_address,
        )
    )
    await session.commit()


def _audit_passkey(
    session: AsyncSession,
    request: Request,
    user: UserRecord,
    *,
    action: str,
    passkey_id: str,
) -> None:
    session.add(
        AuditEvent(
            organization_id=user.organization_id,
            user_id=user.id,
            action=action,
            resource_type="passkey",
            resource_id=passkey_id,
            details={"country": request.headers.get("cf-ipcountry")},
            ip_address=client_ip_from_request(request),
        )
    )


@router.get("/firebase/social/public")
async def get_social_configuration():
    return firebase_social_public_configuration()


@router.post("/firebase/social/session", response_model=SessionResponse)
async def create_social_session(
    data: FirebaseSocialSessionRequest,
    request: Request,
    http_response: Response,
    session: AsyncSession = Depends(get_db),
):
    identity = await verify_firebase_social_id_token(data.id_token)
    provider = str(identity["provider"])
    subject = str(identity["subject"])
    row = await session.scalar(
        select(ExternalIdentity)
        .where(
            ExternalIdentity.provider == provider,
            ExternalIdentity.subject == subject,
        )
        .with_for_update()
    )
    if row is None:
        account = await session.scalar(
            select(User)
            .where(
                func.lower(User.email) == str(identity["email"]),
                User.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ACCOUNT_REGISTRATION_REQUIRED",
                    "message": "Create your AIOS account before using social sign-in.",
                },
            )
        linked = await session.scalar(
            select(ExternalIdentity)
            .where(
                ExternalIdentity.user_id == account.id,
                ExternalIdentity.provider == provider,
            )
            .with_for_update()
        )
        if linked is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SOCIAL_IDENTITY_CONFLICT",
                    "message": "A different provider identity is already linked.",
                },
            )
        row = ExternalIdentity(
            user_id=account.id,
            provider=provider,
            subject=subject,
            email=str(identity["email"]),
            provider_metadata={
                "firebase_uid": identity["firebase_uid"],
                "name": identity["name"],
                "picture": identity["picture"],
            },
        )
        session.add(row)
    else:
        row.email = str(identity["email"])
        row.provider_metadata = {
            "firebase_uid": identity["firebase_uid"],
            "name": identity["name"],
            "picture": identity["picture"],
        }
    row.last_login_at = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SOCIAL_IDENTITY_CONFLICT",
                "message": "This provider identity is already linked.",
            },
        ) from exc

    user = await auth_service.get_user_by_id(session, row.user_id)
    enforce_auth_channel_role(request, user)
    response = await auth_service.issue_pair(session, user)
    await _audit_session(
        session,
        request,
        response,
        user,
        action="auth.social_login",
        details={"provider": provider},
    )
    attach_browser_session_cookies(http_response, response)
    return response


@router.post(
    "/firebase/social/registration/prepare",
    response_model=SocialRegistrationPreparationResponse,
)
async def prepare_social_registration(data: FirebaseSocialSessionRequest):
    identity = await verify_firebase_social_id_token(data.id_token)
    return await create_social_registration(identity)


@router.get("/passkeys/public")
async def get_passkey_configuration():
    return passkey_public_configuration()


@router.get("/passkeys")
async def list_passkeys(
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    rows = (
        (
            await session.execute(
                select(PasskeyCredential)
                .where(PasskeyCredential.user_id == user.id)
                .order_by(PasskeyCredential.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [serialize_passkey(row) for row in rows]


@router.post("/passkeys/registration/options")
async def create_passkey_registration_options(
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return await registration_options(session, user)


@router.post("/passkeys/registration/verify", status_code=status.HTTP_201_CREATED)
async def complete_passkey_registration(
    data: PasskeyRegistrationVerifyRequest,
    request: Request,
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    row = await verify_registration(
        session,
        user,
        ceremony_id=data.ceremony_id,
        credential=data.credential,
        nickname=data.nickname,
    )
    _audit_passkey(
        session,
        request,
        user,
        action="auth.passkey_registered",
        passkey_id=row.id,
    )
    await session.commit()
    return serialize_passkey(row)


@router.post("/passkeys/authentication/options")
async def create_passkey_authentication_options():
    return await authentication_options()


@router.post("/passkeys/authentication/verify", response_model=SessionResponse)
async def complete_passkey_authentication(
    data: PasskeyAuthenticationVerifyRequest,
    request: Request,
    http_response: Response,
    session: AsyncSession = Depends(get_db),
):
    row = await verify_authentication(
        session,
        ceremony_id=data.ceremony_id,
        credential=data.credential,
    )
    user = await auth_service.get_user_by_id(session, row.user_id)
    enforce_auth_channel_role(request, user)
    response = await auth_service.issue_pair(session, user)
    await _audit_session(
        session,
        request,
        response,
        user,
        action="auth.passkey_login",
        details={"passkey_id": row.id},
    )
    attach_browser_session_cookies(http_response, response)
    return response


@router.delete("/passkeys/{passkey_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_passkey(
    passkey_id: str,
    request: Request,
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    row = await session.scalar(
        select(PasskeyCredential).where(
            PasskeyCredential.id == passkey_id,
            PasskeyCredential.user_id == user.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Passkey not found")
    _audit_passkey(
        session,
        request,
        user,
        action="auth.passkey_deleted",
        passkey_id=row.id,
    )
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
