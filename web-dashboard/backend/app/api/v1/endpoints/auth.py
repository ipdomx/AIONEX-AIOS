"""Authentication endpoints."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, auth_service, current_user, oauth2_scheme
from app.db.base import get_db
from app.db.models import AuditEvent, RefreshSession
from app.services.firebase_phone import firebase_public_configuration
from app.services.free_tier import (
    client_ip_from_request,
    get_free_tier_policy,
    get_free_tier_status,
    public_free_tier_policy,
    register_free_account,
)

router = APIRouter()


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    organization_name: str | None = None


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


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
):
    user = await auth_service.authenticate(
        session, form_data.username, form_data.password
    )
    response = await auth_service.issue_pair(session, user)
    await _attach_session_context(
        session,
        request,
        response,
        user,
        action="auth.login",
    )
    return response


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, session: AsyncSession = Depends(get_db)):
    user = await auth_service.register(
        session, data.email, data.password, data.name, data.organization_name
    )
    return {
        "message": "User registered successfully",
        "user": auth_service.serialize_user(user),
    }


@router.get("/free-tier/public")
async def get_public_free_tier(session: AsyncSession = Depends(get_db)):
    policy = await get_free_tier_policy(session)
    await session.commit()
    return public_free_tier_policy(policy)


@router.get("/firebase/phone/public")
async def get_public_firebase_phone_configuration():
    return firebase_public_configuration()


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
async def refresh_token(data: RefreshRequest, session: AsyncSession = Depends(get_db)):
    return await auth_service.refresh(session, data.refresh_token)


@router.post("/password-reset")
async def request_password_reset(data: PasswordResetRequest):
    return {"message": "Password reset request accepted"}


@router.post("/password-reset/confirm")
async def confirm_password_reset(data: PasswordResetConfirm):
    return {"message": "Password reset confirmation accepted"}


@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(user: UserRecord = Depends(current_user)):
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="MFA enrollment is not configured for this deployment",
    )


@router.post("/mfa/verify")
async def verify_mfa(code: str, user: UserRecord = Depends(current_user)):
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="MFA verification is not configured for this deployment",
    )


@router.get("/me")
async def get_current_user(user: UserRecord = Depends(current_user)):
    return auth_service.serialize_user(user)
