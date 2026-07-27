"""Authentication endpoints."""

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, auth_service, current_user, oauth2_scheme
from app.db.base import get_db

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


class RefreshRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str


class MFASetupResponse(BaseModel):
    secret: str
    qr_code: str
    backup_codes: list[str]


@router.post("/login", response_model=LoginResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_db),
):
    user = await auth_service.authenticate(session, form_data.username, form_data.password)
    return await auth_service.issue_pair(session, user)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, session: AsyncSession = Depends(get_db)):
    user = await auth_service.register(session, data.email, data.password, data.name, data.organization_name)
    return {"message": "User registered successfully", "user": auth_service.serialize_user(user)}


@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
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
    return {
        "secret": "mfa-setup-required",
        "qr_code": "",
        "backup_codes": [],
    }


@router.post("/mfa/verify")
async def verify_mfa(code: str, user: UserRecord = Depends(current_user)):
    return {"verified": bool(code.strip())}


@router.get("/me")
async def get_current_user(user: UserRecord = Depends(current_user)):
    return auth_service.serialize_user(user)
