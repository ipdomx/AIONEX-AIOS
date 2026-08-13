from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.auth import UserRecord, pwd_context
from app.db.base import SessionLocal
from app.db.models import Organization, OwnerControlRecord, Role, User
from app.services import owner_telegram_auth


async def _identity(suffix: str) -> tuple[Organization, User, UserRecord]:
    organization = Organization(
        name=f"Telegram Owner Security {suffix}",
        slug=f"telegram-owner-security-{suffix}",
        plan="enterprise",
        status="active",
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        role = Role(
            organization_id=organization.id,
            name="Super Owner",
            status="active",
            system=True,
        )
        session.add(role)
        await session.flush()
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            email=f"telegram-owner-security-{suffix}@example.com",
            name="Telegram Security Owner",
            password_hash=pwd_context.hash(f"TelegramSecurity!{suffix}Aa1"),
            status="active",
        )
        session.add(user)
        await session.commit()
        actor = UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            role="Super Owner",
            password_hash=user.password_hash,
            organization_id=organization.id,
            organization_name=organization.name,
            organization_plan=organization.plan,
            permissions=["*"],
            status="active",
            auth_version=user.auth_version,
        )
        return organization, user, actor


async def _cleanup(organization_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain.in_(
                    {
                        owner_telegram_auth.CHALLENGE_DOMAIN,
                        owner_telegram_auth.SESSION_DOMAIN,
                        owner_telegram_auth.FAILURE_DOMAIN,
                    }
                )
            )
        )
        organization = await session.get(Organization, organization_id)
        if organization is not None:
            await session.delete(organization)
        await session.commit()


@pytest.mark.asyncio
async def test_owner_telegram_second_factor_is_one_time_and_auth_version_bound() -> None:
    suffix = uuid4().hex[:12]
    organization, user, actor = await _identity(suffix)
    try:
        async with SessionLocal() as session:
            challenge = await owner_telegram_auth.issue_challenge(session, actor)
            await session.commit()
            assert len(challenge["code"]) == 10
            assert challenge["code"].isdigit()

            row = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == owner_telegram_auth.CHALLENGE_DOMAIN,
                    OwnerControlRecord.enabled.is_(True),
                )
            )
            assert row is not None
            serialized = json.dumps(row.payload)
            assert challenge["code"] not in serialized
            assert row.payload.get("code_digest")

            snapshot = await owner_telegram_auth.security_snapshot(session, actor)
            assert snapshot["challenge_active"] is True
            assert snapshot["session_active"] is False

            result = await owner_telegram_auth.authenticate(
                session,
                telegram_user_id=700000001,
                chat_id=700000001,
                code=challenge["code"],
            )
            await session.commit()
            assert result["expires_in_seconds"] == owner_telegram_auth.SESSION_TTL_SECONDS

            consumed = await session.get(OwnerControlRecord, row.id)
            assert consumed is not None
            assert consumed.status == "consumed"
            assert consumed.enabled is False
            assert "code_digest" not in consumed.payload

            owner_id = await owner_telegram_auth.require_active_session(
                session,
                telegram_user_id=700000001,
                chat_id=700000001,
            )
            assert owner_id == user.id
            with pytest.raises(
                owner_telegram_auth.TelegramOwnerAuthError,
                match="session_required",
            ):
                await owner_telegram_auth.require_active_session(
                    session,
                    telegram_user_id=700000001,
                    chat_id=700000002,
                )

            stored_user = await session.get(User, user.id)
            assert stored_user is not None
            stored_user.auth_version += 1
            await session.commit()
            with pytest.raises(
                owner_telegram_auth.TelegramOwnerAuthError,
                match="session_invalidated",
            ):
                await owner_telegram_auth.require_active_session(
                    session,
                    telegram_user_id=700000001,
                    chat_id=700000001,
                )
    finally:
        await _cleanup(organization.id)


@pytest.mark.asyncio
async def test_owner_telegram_failed_codes_lock_out_and_dashboard_can_revoke() -> None:
    suffix = uuid4().hex[:12]
    organization, _, actor = await _identity(suffix)
    try:
        async with SessionLocal() as session:
            challenge = await owner_telegram_auth.issue_challenge(session, actor)
            await session.commit()

            for _ in range(owner_telegram_auth.MAX_FAILURES):
                with pytest.raises(
                    owner_telegram_auth.TelegramOwnerAuthError,
                    match="invalid_code",
                ):
                    await owner_telegram_auth.authenticate(
                        session,
                        telegram_user_id=700000003,
                        chat_id=700000003,
                        code="0000000000",
                    )
                await session.commit()

            with pytest.raises(
                owner_telegram_auth.TelegramOwnerAuthError,
                match="locked",
            ):
                await owner_telegram_auth.authenticate(
                    session,
                    telegram_user_id=700000003,
                    chat_id=700000003,
                    code=challenge["code"],
                )

            failure = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == owner_telegram_auth.FAILURE_DOMAIN,
                    OwnerControlRecord.resource_id == "700000003",
                )
            )
            assert failure is not None
            assert failure.status == "locked"
            assert int(failure.payload["failures"]) == owner_telegram_auth.MAX_FAILURES

            # A different allowlisted identity can still authenticate with a fresh
            # owner-issued code, and the dashboard can revoke that session globally.
            replacement = await owner_telegram_auth.issue_challenge(session, actor)
            await session.commit()
            await owner_telegram_auth.authenticate(
                session,
                telegram_user_id=700000004,
                chat_id=700000004,
                code=replacement["code"],
            )
            await session.commit()
            assert (await owner_telegram_auth.security_snapshot(session, actor))[
                "session_active"
            ] is True
            assert await owner_telegram_auth.revoke_owner_sessions(session, actor) == 1
            await session.commit()
            assert (await owner_telegram_auth.security_snapshot(session, actor))[
                "session_active"
            ] is False
    finally:
        await _cleanup(organization.id)
