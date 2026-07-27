"""Production authentication and session primitives for the dashboard backend."""
from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.identity_store import IdentityUserRecord, identity_store, utc_now

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
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
    status: str = "active"


class AuthService:
    def __init__(self) -> None:
        self._refresh_tokens: dict[str, dict[str, Any]] = {}
        self._revoked_access_tokens: set[str] = set()
        self._bootstrap_owner()

    def _bootstrap_owner(self) -> None:
        owner_email = os.getenv("AIOS_BOOTSTRAP_OWNER_EMAIL", "owner@aionex.local").strip().lower()
        owner_password = os.getenv("AIOS_BOOTSTRAP_OWNER_PASSWORD", "ChangeMeNow!123")

        existing = identity_store.find_user_by_email(owner_email)
        if existing:
            existing.password_hash = pwd_context.hash(owner_password)
            existing.status = "active"
            existing.updated_at = utc_now()
            return

        identity_store.users["owner-1"] = IdentityUserRecord(
            id="owner-1",
            email=owner_email,
            name="AIONEX Owner",
            role_id="role-super-owner",
            organization_id="aionex-org",
            password_hash=pwd_context.hash(owner_password),
            status="active",
            last_active=utc_now(),
        )

    def _to_user_record(self, user: IdentityUserRecord) -> UserRecord:
        role = identity_store.get_role(user.role_id)
        organization = identity_store.get_organization(user.organization_id)
        return UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            role=role.name,
            password_hash=user.password_hash,
            organization_id=organization.id,
            organization_name=organization.name,
            permissions=list(role.permissions),
            status=user.status,
        )

    def register(self, email: str, password: str, name: str, organization_name: str | None = None) -> UserRecord:
        normalized = email.strip().lower()
        if identity_store.find_user_by_email(normalized):
            raise HTTPException(status_code=409, detail="Email already registered")
        if len(password) < settings.PASSWORD_MIN_LENGTH:
            raise HTTPException(status_code=422, detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters")

        user_id = secrets.token_urlsafe(12)
        organization_id = secrets.token_urlsafe(10)
        organization_display_name = (organization_name or f"{name.strip()} Organization").strip()
        identity_store.organizations[organization_id] = identity_store.organizations["aionex-org"].__class__(
            id=organization_id,
            name=organization_display_name,
            slug=f"org-{organization_id.lower()}",
            owner_user_id=user_id,
        )
        owner_role = identity_store.get_role("role-owner")
        identity_user = IdentityUserRecord(
            id=user_id,
            email=normalized,
            name=name.strip(),
            role_id=owner_role.id,
            organization_id=organization_id,
            password_hash=pwd_context.hash(password),
            status="active",
            last_active=utc_now(),
        )
        identity_store.users[user_id] = identity_user
        identity_store.record_audit(user_id, "register", "user", user_id, {"organization_id": organization_id})
        return self._to_user_record(identity_user)

    def authenticate(self, email: str, password: str) -> UserRecord:
        identity_user = identity_store.find_user_by_email(email)
        if identity_user is None or not pwd_context.verify(password, identity_user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        if identity_user.status not in {"active", "online"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is not active")
        identity_user.last_active = utc_now()
        identity_store.record_audit(identity_user.id, "login", "session", identity_user.id)
        return self._to_user_record(identity_user)

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
        identity_store.sessions.setdefault(user.id, []).append({
            "id": digest[:16],
            "created_at": utc_now(),
            "last_active": utc_now(),
            "is_current": True,
        })
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
        return self._to_user_record(identity_store.get_user(user_id))

    def serialize_user(self, user: UserRecord) -> dict[str, Any]:
        identity_user = identity_store.get_user(user.id)
        payload = identity_store.serialize_user(identity_user)
        payload["organization"] = {
            "id": user.organization_id,
            "name": user.organization_name,
            "plan": identity_store.get_organization(user.organization_id).plan,
        }
        return payload


auth_service = AuthService()


def current_user(token: str = Depends(oauth2_scheme)) -> UserRecord:
    payload = auth_service.decode_access_token(token)
    return auth_service.get_user_by_id(str(payload["sub"]))


def require_permissions(*required: str) -> Callable[[UserRecord], UserRecord]:
    def dependency(user: UserRecord = Depends(current_user)) -> UserRecord:
        granted = set(user.permissions)
        if "*" in granted or all(permission in granted for permission in required):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    return dependency
