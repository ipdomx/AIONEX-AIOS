"""Database-backed authentication and session primitives for the dashboard backend."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import SessionLocal, get_db
from app.db.models import Organization, Permission, RefreshSession, Role, RolePermission, User

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    organization_plan: str
    permissions: list[str]
    status: str = "active"


class AuthService:
    async def _to_user_record(self, session: AsyncSession, user: User) -> UserRecord:
        role_name = "Unassigned"
        permissions: list[str] = []

        if user.role_id:
            role = await session.get(Role, user.role_id)
            if role is not None:
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
        existing = await session.scalar(select(User).where(User.email == normalized, User.deleted_at.is_(None)))
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

        permission_rows = (await session.execute(select(Permission))).scalars().all()
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

    async def _authenticate_with_session(self, session: AsyncSession, email: str, password: str) -> UserRecord:
        normalized = email.strip().lower()
        user = await session.scalar(select(User).where(User.email == normalized, User.deleted_at.is_(None)))
        if user is None or not pwd_context.verify(password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        if user.status not in {"active", "online"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is not active")
        return await self._to_user_record(session, user)

    def authenticate(self, *args: Any):
        if len(args) == 3 and isinstance(args[0], AsyncSession):
            session, email, password = args
            return self._authenticate_with_session(session, email, password)
        if len(args) == 2:
            email, password = args

            async def _run() -> UserRecord:
                async with SessionLocal() as session:
                    return await self._authenticate_with_session(session, email, password)

            return _run()
        raise TypeError("authenticate expects (session, email, password) or (email, password)")

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

    async def create_refresh_token(self, session: AsyncSession, user: UserRecord) -> str:
        raw = secrets.token_urlsafe(48)
        session.add(
            RefreshSession(
                user_id=user.id,
                token_hash=_hash_refresh_token(raw),
                expires_at=_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            )
        )
        await session.flush()
        return raw

    async def issue_pair(self, session: AsyncSession, user: UserRecord) -> dict[str, Any]:
        refresh_token = await self.create_refresh_token(session, user)
        await session.commit()
        return {
            "access_token": self.create_access_token(user),
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": self.serialize_user(user),
        }

    async def refresh(self, session: AsyncSession, refresh_token: str) -> dict[str, Any]:
        digest = _hash_refresh_token(refresh_token)
        record = await session.scalar(select(RefreshSession).where(RefreshSession.token_hash == digest))
        if record is None or record.revoked_at is not None or _as_utc(record.expires_at) <= _now():
            raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

        record.revoked_at = _now()
        user = await self.get_user_by_id(session, record.user_id)
        new_refresh_token = await self.create_refresh_token(session, user)
        await session.commit()
        return {
            "access_token": self.create_access_token(user),
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "user": self.serialize_user(user),
        }

    def decode_access_token(self, token: str) -> dict[str, Any]:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        except JWTError as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        return payload

    async def revoke_access_token(self, _token: str) -> None:
        return None

    async def get_user_by_id(self, session: AsyncSession, user_id: str) -> UserRecord:
        user = await session.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
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
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> UserRecord:
    payload = auth_service.decode_access_token(token)
    return await auth_service.get_user_by_id(session, str(payload["sub"]))


def require_permissions(*required: str) -> Callable[[UserRecord], UserRecord]:
    async def dependency(user: UserRecord = Depends(current_user)) -> UserRecord:
        granted = set(user.permissions)
        if "*" in granted or all(permission in granted for permission in required):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    return dependency
