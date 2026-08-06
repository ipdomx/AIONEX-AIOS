"""Authentication endpoints."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any

from app.core.auth import (
    UserRecord,
    auth_service,
    current_user,
    enforce_auth_channel_role,
    oauth2_scheme,
)
from app.db.base import get_db
from app.db.models import AuditEvent, ExternalIdentity, RefreshSession, User, uuid_str
from app.services.firebase_phone import (
    firebase_phone_readiness,
    firebase_public_configuration,
)
from app.services.firebase_social import consume_social_registration
from app.services.account_security import (
    confirm_mfa_setup,
    confirm_password_reset as confirm_password_reset_service,
    consume_mfa_challenge,
    create_mfa_challenge,
    disable_mfa,
    mfa_enabled,
    mfa_status,
    request_password_reset as request_password_reset_service,
    start_mfa_setup,
)
from app.services.free_tier import (
    client_ip_from_request,
    get_free_tier_policy,
    get_free_tier_status,
    public_free_tier_policy,
    register_free_account,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class MFAChallengeResponse(BaseModel):
    mfa_required: bool = True
    challenge_token: str
    expires_in: int


class MFAChallengeVerify(BaseModel):
    challenge_token: str = Field(min_length=20, max_length=4096)
    code: str = Field(min_length=6, max_length=32)


class MFACodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MFADisableRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    code: str = Field(min_length=6, max_length=32)


class FreeRegistrationTelemetry(BaseModel):
    timezone: str | None = Field(default=None, max_length=80)
    language: str | None = Field(default=None, max_length=32)
    platform: str | None = Field(default=None, max_length=160)
    user_agent: str | None = Field(default=None, max_length=512)
    screen: str | None = Field(default=None, max_length=80)
    screen_width: int | None = Field(default=None, ge=0, le=100_000)
    screen_height: int | None = Field(default=None, ge=0, le=100_000)
    color_depth: int | None = Field(default=None, ge=0, le=256)
    device_memory_gb: float | None = Field(default=None, ge=0, le=1024)
    hardware_concurrency: int | None = Field(default=None, ge=0, le=4096)
    max_touch_points: int | None = Field(default=None, ge=0, le=1000)
    cookie_enabled: bool | None = None
    do_not_track: bool | None = None
    connection_type: str | None = Field(default=None, max_length=40)
    effective_type: str | None = Field(default=None, max_length=40)
    downlink_mbps: float | None = Field(default=None, ge=0, le=1_000_000)
    rtt_ms: int | None = Field(default=None, ge=0, le=1_000_000)
    save_data: bool | None = None
    referrer: str | None = Field(default=None, max_length=500)
    vendor: str | None = Field(default=None, max_length=160)
    webdriver: bool | None = None


class FreeRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str
    name: str = Field(min_length=2, max_length=200)
    birth_date: date
    country_code: str = Field(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")
    phone_number: str = Field(
        min_length=8,
        max_length=20,
        pattern=r"^\+[1-9][0-9]{7,14}$",
    )
    firebase_id_token: str | None = Field(default=None, min_length=100, max_length=8192)
    social_registration_token: str | None = Field(
        default=None,
        min_length=20,
        max_length=256,
    )
    consent_accepted: bool
    consent_version: str = Field(min_length=4, max_length=80)
    telemetry: FreeRegistrationTelemetry = Field(
        default_factory=FreeRegistrationTelemetry
    )


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


class MFASetupResponse(BaseModel):
    secret: str
    qr_code: str
    backup_codes: list[str]


async def _attach_session_context(
    session: AsyncSession,
    request: Request,
    response: dict[str, Any],
    user: UserRecord,
    *,
    action: str,
) -> None:
    refresh_token = str(response["refresh_token"])
    token_hash = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
    refresh_session = await session.scalar(
        select(RefreshSession).where(RefreshSession.token_hash == token_hash)
    )
    ip_address = client_ip_from_request(request)
    if refresh_session is not None:
        refresh_session.ip_address = ip_address
        refresh_session.user_agent = (request.headers.get("user-agent") or "")[:2000]
    db_user = await session.get(User, user.id)
    if db_user is not None:
        db_user.last_active_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            organization_id=user.organization_id,
            user_id=user.id,
            action=action,
            resource_type="session",
            resource_id=refresh_session.id if refresh_session is not None else None,
            details={"country": request.headers.get("cf-ipcountry")},
            ip_address=ip_address,
        )
    )
    await session.commit()


@router.post("/login", response_model=LoginResponse | MFAChallengeResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
):
    user = await auth_service.authenticate(
        session, form_data.username, form_data.password
    )
    enforce_auth_channel_role(request, user)
    if await mfa_enabled(session, user.id):
        return create_mfa_challenge(user)
    response = await auth_service.issue_pair(session, user)
    await _attach_session_context(
        session,
        request,
        response,
        user,
        action="auth.login",
    )
    return response


@router.get("/free-tier/public")
async def get_public_free_tier(session: AsyncSession = Depends(get_db)):
    policy = await get_free_tier_policy(session)
    await session.commit()
    return public_free_tier_policy(policy)


@router.get("/firebase/phone/public")
async def get_public_firebase_phone_configuration():
    return firebase_public_configuration()


@router.get("/firebase/phone/readiness")
async def get_public_firebase_phone_readiness(
    phone_number: str = Query(
        min_length=8,
        max_length=20,
        pattern=r"^\+[1-9][0-9]{7,14}$",
    ),
    origin: str | None = Query(default=None, max_length=512),
):
    return firebase_phone_readiness(phone_number, origin)


@router.post(
    "/register/free",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_free(
    data: FreeRegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    user = await register_free_account(
        session,
        request,
        username=data.username,
        email=str(data.email),
        password=data.password,
        name=data.name,
        birth_date=data.birth_date,
        country_code=data.country_code,
        phone_number=data.phone_number,
        firebase_id_token=data.firebase_id_token,
        consent_accepted=data.consent_accepted,
        consent_version=data.consent_version,
        telemetry=data.telemetry.model_dump(exclude_none=True),
    )
    if data.social_registration_token:
        social_identity = await consume_social_registration(
            data.social_registration_token
        )
        if str(social_identity["email"]).strip().lower() != user.email:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "SOCIAL_EMAIL_MISMATCH",
                    "message": (
                        "Registration email must match the verified social identity."
                    ),
                },
            )
        external_identity = ExternalIdentity(
            id=uuid_str(),
            user_id=user.id,
            provider=str(social_identity["provider"]),
            subject=str(social_identity["subject"]),
            email=user.email,
            provider_metadata={
                "firebase_uid": social_identity["firebase_uid"],
                "name": social_identity.get("name"),
                "picture": social_identity.get("picture"),
            },
            last_login_at=datetime.now(UTC),
        )
        session.add(external_identity)
        session.add(
            AuditEvent(
                organization_id=user.organization_id,
                user_id=user.id,
                action="auth.social_identity_registered",
                resource_type="external_identity",
                resource_id=external_identity.id,
                details={"provider": external_identity.provider},
                ip_address=client_ip_from_request(request),
            )
        )
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SOCIAL_IDENTITY_CONFLICT",
                    "message": "This social identity is already registered.",
                },
            ) from exc
    user_record = await auth_service.get_user_by_id(session, user.id)
    response = await auth_service.issue_pair(session, user_record)
    await _attach_session_context(
        session,
        request,
        response,
        user_record,
        action="auth.free_login",
    )
    return response


@router.get("/free-tier")
async def get_current_free_tier(
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    result = await get_free_tier_status(session, user)
    await session.commit()
    return result


@router.post("/logout")
async def logout(
    data: LogoutRequest | None = None,
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
):
    payload = auth_service._decode_access_token_payload(token)
    if data is not None and data.refresh_token:
        await auth_service.revoke_refresh_token(
            session,
            data.refresh_token,
            user_id=str(payload["sub"]),
        )
    await auth_service.revoke_access_token(token)
    return {"message": "Logged out successfully"}


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    data: RefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    user = await auth_service.get_refresh_user(session, data.refresh_token)
    enforce_auth_channel_role(request, user)
    response = await auth_service.refresh(session, data.refresh_token)
    await _attach_session_context(
        session, request, response, user, action="auth.refresh"
    )
    return response


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    data: PasswordResetRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    return await request_password_reset_service(session, request, str(data.email))


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    data: PasswordResetConfirm,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    return await confirm_password_reset_service(
        session, request, data.token, data.new_password
    )


@router.get("/mfa/status")
async def get_mfa_status(
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return await mfa_status(session, user.id)


@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return await start_mfa_setup(session, user)


@router.post("/mfa/verify")
async def verify_mfa(
    data: MFACodeRequest,
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return await confirm_mfa_setup(session, user, data.code)


@router.post("/mfa/disable")
async def disable_mfa_endpoint(
    data: MFADisableRequest,
    user: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    return await disable_mfa(
        session, user, data.current_password, data.code
    )


@router.post("/mfa/challenge", response_model=LoginResponse)
async def verify_mfa_challenge(
    data: MFAChallengeVerify,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    user = await consume_mfa_challenge(
        session, data.challenge_token, data.code
    )
    enforce_auth_channel_role(request, user)
    response = await auth_service.issue_pair(session, user)
    await _attach_session_context(
        session, request, response, user, action="auth.mfa_login"
    )
    return response


@router.get("/me")
async def get_current_user(user: UserRecord = Depends(current_user)):
    return auth_service.serialize_user(user)
