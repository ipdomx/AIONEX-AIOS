"""Database-backed authentication and session primitives for the dashboard backend."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError as JWTError
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.base import get_db
from app.db.models import (
    Organization,
    Permission,
    RefreshSession,
    Role,
    RolePermission,
    User,
)
from app.db.redis import get_redis

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
logger = get_logger(__name__)

ACTIVE_USER_STATUSES = frozenset({"active", "online"})
ACTIVE_ORGANIZATION_STATUSES = frozenset({"active", "trial"})
ACCESS_TOKEN_REVOCATION_PREFIX = "aionex:auth:revoked:access:"
DEFAULT_PUBLIC_PORTAL_ORIGINS = (
    "https://ai.vip-e.net",
    "https://vip-e.net",
    "https://www.vip-e.net",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _access_token_revocation_key(token: str) -> str:
    return f"{ACCESS_TOKEN_REVOCATION_PREFIX}{_hash_token(token)}"


def _normalized_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port
    suffix = "" if port == default_port else f":{port}"
    return f"{parsed.scheme}://{parsed.hostname.lower()}{suffix}"


def public_portal_origins() -> set[str]:
    raw = os.getenv("AIOS_PUBLIC_PORTAL_ORIGINS", "").strip()
    values: list[str]
    if not raw:
        values = list(DEFAULT_PUBLIC_PORTAL_ORIGINS)
    elif raw.startswith("["):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = []
        values = [str(item) for item in decoded] if isinstance(decoded, list) else []
    else:
        values = raw.split(",")
    return {
        normalized
        for value in values
        if (normalized := _normalized_origin(value)) is not None
    }


def enforce_auth_channel_role(request: Request, user: "UserRecord") -> None:
    """Keep public users and the Super Owner on separate ingress channels."""

    auth_channel = request.headers.get("x-aios-auth-channel", "").strip().lower()
    origin = _normalized_origin(request.headers.get("origin", ""))
    public_request = auth_channel == "public" or origin in public_portal_origins()
    if public_request and user.role == "Super Owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign-in is unavailable for this account",
        )
    if auth_channel == "private" and user.role != "Super Owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Control-plane access denied",
        )


def _authentication_state_unavailable(exc: Exception) -> HTTPException:
    logger.error(
        "Access-token revocation store unavailable",
        error_type=type(exc).__name__,
    )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication state is temporarily unavailable",
        headers={"Retry-After": "5"},
    )


@dataclass
class UserRecord:
    id: str
    email: str
    name: str
    role: str
    password_hash: str
    organization_id: str
    organization_name: str
    organization_plan: str
    permissions: list[str]
    status: str = "active"
    auth_version: int = 0


class AuthService:
    async def _to_user_record(self, session: AsyncSession, user: User) -> UserRecord:
        if user.status not in ACTIVE_USER_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is not active",
            )
        role_name = "Unassigned"
        permissions: list[str] = []
        if user.role_id:
            role = await session.get(Role, user.role_id)
            if role is not None:
                if role.status != "active":
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Assigned role is suspended",
                    )
                role_name = role.name
                result = await session.execute(
                    select(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == role.id)
                )
                permissions = list(result.scalars().all())
        organization = await session.get(Organization, user.organization_id)
        if organization is None:
            raise HTTPException(status_code=500, detail="User organization is missing")
        if organization.status not in ACTIVE_ORGANIZATION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User organization is not active",
            )
        return UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            role=role_name,
            password_hash=user.password_hash,
            organization_id=organization.id,
            organization_name=organization.name,
            organization_plan=organization.plan,
            permissions=permissions,
            status=user.status,
            auth_version=user.auth_version,
        )

    async def register(
        self,
        session: AsyncSession,
        email: str,
        password: str,
        name: str,
        organization_name: str | None = None,
    ) -> UserRecord:
        normalized = email.strip().lower()
        existing = await session.scalar(
            select(User).where(User.email == normalized, User.deleted_at.is_(None))
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="Email already registered")
        if len(password) < settings.PASSWORD_MIN_LENGTH:
            raise HTTPException(
                status_code=422,
                detail=f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters",
            )
        organization = Organization(
            name=(organization_name or f"{name.strip()} Organization").strip(),
            slug=f"org-{secrets.token_urlsafe(8).lower()}",
            plan="enterprise",
            status="active",
        )
        session.add(organization)
        await session.flush()
        role = Role(
            organization_id=organization.id,
            name="Owner",
            description="Organization owner",
            system=False,
        )
        session.add(role)
        await session.flush()
        permission_rows = (
            (await session.execute(select(Permission).where(Permission.code != "*")))
            .scalars()
            .all()
        )
        for permission in permission_rows:
            session.add(RolePermission(role_id=role.id, permission_id=permission.id))
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            email=normalized,
            name=name.strip(),
            password_hash=pwd_context.hash(password),
            status="active",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return await self._to_user_record(session, user)

    async def authenticate(
        self, session: AsyncSession, email: str, password: str
    ) -> UserRecord:
        normalized = email.strip().lower()
        user = await session.scalar(
            select(User).where(User.email == normalized, User.deleted_at.is_(None))
        )
        if user is None or not pwd_context.verify(password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        if user.status not in ACTIVE_USER_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is not active",
            )
        return await self._to_user_record(session, user)

    def _access_payload(self, user: UserRecord) -> dict[str, Any]:
        issued_at = _now()
        expires_at = issued_at + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        return {
            "sub": user.id,
            "email": user.email,
            "role": user.role,
            "permissions": user.permissions,
            "organization_id": user.organization_id,
            "auth_version": user.auth_version,
            "iat": int(issued_at.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": secrets.token_urlsafe(16),
            "type": "access",
        }

    def create_access_token(self, user: UserRecord) -> str:
        return jwt.encode(
            self._access_payload(user),
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )

    async def create_refresh_token(
        self, session: AsyncSession, user: UserRecord
    ) -> str:
        raw = secrets.token_urlsafe(48)
        session.add(
            RefreshSession(
                user_id=user.id,
                token_hash=_hash_token(raw),
                expires_at=_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            )
        )
        await session.flush()
        return raw

    async def issue_pair(
        self, session: AsyncSession, user: UserRecord
    ) -> dict[str, Any]:
        refresh_token = await self.create_refresh_token(session, user)
        await session.commit()
        return {
            "access_token": self.create_access_token(user),
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": self.serialize_user(user),
        }

    async def refresh(
        self, session: AsyncSession, refresh_token: str
    ) -> dict[str, Any]:
        record = await session.scalar(
            select(RefreshSession)
            .where(RefreshSession.token_hash == _hash_token(refresh_token))
            .with_for_update()
        )
        if (
            record is None
            or record.revoked_at is not None
            or _as_utc(record.expires_at) <= _now()
        ):
            raise HTTPException(
                status_code=401, detail="Invalid or expired refresh token"
            )
        record.revoked_at = _now()
        try:
            user = await self.get_user_by_id(session, record.user_id)
        except HTTPException:
            # A refresh token presented after account or organization suspension
            # is consumed permanently instead of becoming valid after reactivation.
            await session.commit()
            raise
        new_refresh_token = await self.create_refresh_token(session, user)
        await session.commit()
        return {
            "access_token": self.create_access_token(user),
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": self.serialize_user(user),
        }

    async def get_refresh_user(
        self, session: AsyncSession, refresh_token: str
    ) -> UserRecord:
        record = await session.scalar(
            select(RefreshSession).where(
                RefreshSession.token_hash == _hash_token(refresh_token),
                RefreshSession.revoked_at.is_(None),
            )
        )
        if record is None or _as_utc(record.expires_at) <= _now():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )
        return await self.get_user_by_id(session, record.user_id)

    def _decode_access_token_payload(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
        except JWTError as exc:
            raise HTTPException(
                status_code=401, detail="Invalid or expired token"
            ) from exc
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload

    async def decode_access_token(self, token: str) -> dict[str, Any]:
        payload = self._decode_access_token_payload(token)
        try:
            redis = await get_redis()
            revoked = await redis.exists(_access_token_revocation_key(token))
        except Exception as exc:
            raise _authentication_state_unavailable(exc) from exc
        if revoked:
            raise HTTPException(status_code=401, detail="Token has been revoked")
        return payload

    async def revoke_access_token(self, token: str) -> None:
        payload = self._decode_access_token_payload(token)
        ttl_seconds = max(1, int(payload["exp"]) - int(_now().timestamp()))
        try:
            redis = await get_redis()
            persisted = await redis.set(
                _access_token_revocation_key(token),
                "1",
                ex=ttl_seconds,
            )
            if not persisted:
                raise RuntimeError("Redis did not persist access-token revocation")
        except Exception as exc:
            raise _authentication_state_unavailable(exc) from exc

    async def revoke_refresh_token(
        self,
        session: AsyncSession,
        refresh_token: str,
        *,
        user_id: str,
    ) -> bool:
        """Revoke one refresh session without exposing token ownership."""

        record = await session.scalar(
            select(RefreshSession)
            .where(
                RefreshSession.token_hash == _hash_token(refresh_token),
                RefreshSession.user_id == user_id,
            )
            .with_for_update()
        )
        if record is None:
            return False
        if record.revoked_at is None:
            record.revoked_at = _now()
            await session.commit()
        return True

    async def get_user_by_id(self, session: AsyncSession, user_id: str) -> UserRecord:
        user = await session.scalar(
            select(User).where(User.id == user_id, User.deleted_at.is_(None))
        )
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return await self._to_user_record(session, user)

    def serialize_user(self, user: UserRecord) -> dict[str, Any]:
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "status": user.status,
            "permissions": user.permissions,
            "organization": {
                "id": user.organization_id,
                "name": user.organization_name,
                "plan": user.organization_plan,
            },
        }


auth_service = AuthService()


async def current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> UserRecord:
    payload = await auth_service.decode_access_token(token)
    user = await auth_service.get_user_by_id(session, str(payload["sub"]))
    if int(payload.get("auth_version", 0)) != user.auth_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is no longer valid",
        )
    enforce_auth_channel_role(request, user)
    return user


def require_permissions(*required: str) -> Callable[[UserRecord], UserRecord]:
    async def dependency(user: UserRecord = Depends(current_user)) -> UserRecord:
        granted = set(user.permissions)
        if "*" in granted or all(permission in granted for permission in required):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    return dependency


async def require_super_owner(user: UserRecord = Depends(current_user)) -> UserRecord:
    """Restrict global platform controls to the bootstrap Super Owner role."""
    if user.role == "Super Owner":
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Super Owner access required",
    )
