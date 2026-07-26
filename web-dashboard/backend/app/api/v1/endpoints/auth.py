"""Authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    mfa_code: str | None = None

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
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate user and return tokens."""
    return {
        "access_token": "mock_token",
        "refresh_token": "mock_refresh",
        "token_type": "bearer",
        "expires_in": 1800,
        "user": {
            "id": "mock-user-id",
            "email": form_data.username,
            "name": "Alex Chen",
            "role": "Super Owner",
        },
    }

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest):
    """Register new user and organization."""
    return {"message": "User registered successfully", "user_id": "mock-id"}

@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    """Logout user and invalidate token."""
    return {"message": "Logged out successfully"}

@router.post("/refresh")
async def refresh_token(refresh_token: str):
    """Refresh access token."""
    return {
        "access_token": "new_mock_token",
        "token_type": "bearer",
        "expires_in": 1800,
    }

@router.post("/password-reset")
async def request_password_reset(data: PasswordResetRequest):
    """Request password reset."""
    return {"message": "Password reset email sent"}

@router.post("/password-reset/confirm")
async def confirm_password_reset(data: PasswordResetConfirm):
    """Confirm password reset."""
    return {"message": "Password reset successful"}

@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(token: str = Depends(oauth2_scheme)):
    """Setup MFA for user."""
    return {
        "secret": "mock-secret",
        "qr_code": "data:image/png;base64,mock",
        "backup_codes": ["code1", "code2", "code3", "code4", "code5"],
    }

@router.post("/mfa/verify")
async def verify_mfa(code: str, token: str = Depends(oauth2_scheme)):
    """Verify MFA code."""
    return {"verified": True}

@router.get("/me")
async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Get current authenticated user."""
    return {
        "id": "mock-user-id",
        "email": "alex@aionex.io",
        "name": "Alex Chen",
        "avatar": None,
        "role": "Super Owner",
        "status": "online",
        "organization": {
            "id": "mock-org-id",
            "name": "AIONEX Corp",
            "plan": "enterprise",
        },
        "permissions": ["*"],
    }
