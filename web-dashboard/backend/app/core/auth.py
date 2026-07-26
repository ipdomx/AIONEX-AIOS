"""Production authentication and session primitives for the dashboard backend."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class UserRecord:
    id: str
    email: str
    name: str
    role: str
    password_hash: str
    organization_id: str
    organization_name: str
    permissions: list[str]
    status: str = "online"


class AuthService:
    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}
        self._refresh_tokens: dict[str, dict[str, Any]] = {}
        self._revoked_access_tokens: set[str] = set()
        self._bootstrap_owner()

    def _bootstrap_owner(self) -> None:
        email = "owner@aionex.local"
        if email in self._users:
            return
        self._users[email] = UserRecord(
            id="owner-1",
            email=email,
            name="AIONEX Owner",
            role="Super Owner",
            password_hash=pwd_context.hash("ChangeMeNow!123"),
            organization_id="aionex-org",
            organization_name="AIONEX Corp",
            permissions=["*"],
        )

    def register(self, email: str, password: str, name: str, organization_name: str | None = None) -> UserRecord:
        normalized = email.strip().lower()
        if normalized in self._users:
            raise HTTPException(status_code=409, detail="Email already registered")
        if len(password) < settings.PASSWORD_MIN_LENGTH:
            raise HTTPException(status_code=422, detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters")
        user_id = secrets.token_urlsafe(12)
        org_id = secrets.token_urlsafe(10)
        user = UserRecord(
            id=user_id,
            email=normalized,
            name=name.strip(),
            role="Owner",
            password_hash=pwd_context.hash(password),
            organization_id=org_id,
            organization_name=(organization_name or f"{name.strip()} Organization").strip(),
            permissions=["projects:read", "projects:write", "profile:read"],
        )
        self._users[normalized] = user
        return user

    def authenticate(self, email: str, password: str) -> UserRecord:
        user = self._users.get(email.strip().lower())
        if user is None or not pwd_context.verify(password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        return user

    def _access_payload(self, user: UserRecord) -> dict[str, Any]:
        issued_at = _now()
        expires_at = issued_at + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        return {
            "sub": user.id,
            "email": user.email,
            "role": user.role,
            "permissions": user.permissions,
            "organization_id": user.organization_id,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": secrets.token_urlsafe(16),
            "type": "access",
        }

    def create_access_token(self, user: UserRecord) -> str:
        return jwt.encode(self._access_payload(user), settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    def create_refresh_token(self, user: UserRecord) -> str:
        raw = secrets.token_urlsafe(48)
        digest = _hash_refresh_token(raw)
        self._refresh_tokens[digest] = {
            "user_id": user.id,
            "expires_at": _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            "revoked": False,
        }
        return raw

    def issue_pair(self, user: UserRecord) -> dict[str, Any]:
        return {
            "access_token": self.create_access_token(user),
            "refresh_token": self.create_refresh_token(user),
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": self.serialize_user(user),
        }

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        digest = _hash_refresh_token(refresh_token)
        record = self._refresh_tokens.get(digest)
        if record is None or record["revoked"] or record["expires_at"] <= _now():
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
        user = self.get_user_by_id(record["user_id"])
        record["revoked"] = True
        return self.issue_pair(user)

    def decode_access_token(self, token: str) -> dict[str, Any]:
        if token in self._revoked_access_tokens:
            raise HTTPException(status_code=401, detail="Token has been revoked")
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except JWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload

    def revoke_access_token(self, token: str) -> None:
        self._revoked_access_tokens.add(token)

    def get_user_by_id(self, user_id: str) -> UserRecord:
        for user in self._users.values():
            if user.id == user_id:
                return user
        raise HTTPException(status_code=404, detail="User not found")

    def serialize_user(self, user: UserRecord) -> dict[str, Any]:
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "avatar": None,
            "role": user.role,
            "status": user.status,
            "organization": {
                "id": user.organization_id,
                "name": user.organization_name,
                "plan": "enterprise",
            },
            "permissions": user.permissions,
        }


auth_service = AuthService()


def current_user(token: str = Depends(oauth2_scheme)) -> UserRecord:
    payload = auth_service.decode_access_token(token)
    return auth_service.get_user_by_id(str(payload["sub"]))
