from __future__ import annotations

import json
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.auth import UserRecord, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    CommunicationEndpoint,
    ExternalIdentity,
    Organization,
    OwnerControlRecord,
    Role,
    User,
)
from app.services import user_telegram_auth


async def _user_identity(suffix: str) -> tuple[Organization, User, UserRecord]:
    organization = Organization(
        name=f"Telegram User {suffix}",
        slug=f"telegram-user-{suffix}",
        plan="free",
        status="active",
    )
    async with SessionLocal() as session:
        session.add(organization)
        await session.flush()
        role = Role(
            organization_id=organization.id,
            name="Free User",
            status="active",
            system=True,
        )
        session.add(role)
        await session.flush()
        user = User(
            organization_id=organization.id,
            role_id=role.id,
            email=f"telegram-user-{suffix}@example.com",
            name="Telegram User",
            password_hash=pwd_context.hash(f"TelegramUser!{suffix}Aa1"),
            status="active",
        )
        session.add(user)
        await session.commit()
        actor = UserRecord(
            id=user.id,
            email=user.email,
            name=user.name,
            role="Free User",
            password_hash=user.password_hash,
            organization_id=organization.id,
            organization_name=organization.name,
            organization_plan=organization.plan,
            permissions=["projects:read", "billing:read"],
            status="active",
            auth_version=user.auth_version,
        )
        return organization, user, actor


async def _cleanup(organization_id: str, user_id: str) -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain == user_telegram_auth.CHALLENGE_DOMAIN,
                OwnerControlRecord.resource_id == user_id,
            )
        )
        organization = await session.get(Organization, organization_id)
        if organization is not None:
            await session.delete(organization)
        await session.commit()


@pytest.mark.asyncio
async def test_user_telegram_link_is_durable_one_time_and_auth_version_bound() -> None:
    suffix = uuid4().hex[:12]
    organization, user, actor = await _user_identity(suffix)
    try:
        async with SessionLocal() as session:
            challenge = await user_telegram_auth.issue_link_challenge(session, actor)
            await session.commit()
            assert len(challenge["code"]) == 16

            row = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == user_telegram_auth.CHALLENGE_DOMAIN,
                    OwnerControlRecord.resource_id == user.id,
                )
            )
            assert row is not None
            serialized = json.dumps(row.payload)
            assert challenge["code"] not in serialized
            assert row.payload.get("code_digest")

            linked_actor = await user_telegram_auth.consume_link_challenge(
                session,
                telegram_user_id=720000001,
                chat_id=720000001,
                code=challenge["code"],
                username="verified_user",
            )
            await session.commit()
            assert linked_actor.id == user.id

            identity = await session.scalar(
                select(ExternalIdentity).where(
                    ExternalIdentity.provider == user_telegram_auth.PROVIDER,
                    ExternalIdentity.user_id == user.id,
                )
            )
            assert identity is not None
            assert identity.subject == "720000001"
            assert identity.provider_metadata["chat_id"] == "720000001"
            assert identity.provider_metadata["verified_by"] == "portal_one_time_challenge"

            endpoint = await session.scalar(
                select(CommunicationEndpoint).where(
                    CommunicationEndpoint.user_id == user.id,
                    CommunicationEndpoint.channel == "telegram",
                    CommunicationEndpoint.status == "active",
                )
            )
            assert endpoint is not None
            assert endpoint.verified_at is not None
            assert endpoint.endpoint_metadata["bot_scope"] == "user"
            assert endpoint.address_ciphertext != "720000001"

            with pytest.raises(
                user_telegram_auth.UserTelegramAuthError,
                match="invalid-link-code",
            ):
                await user_telegram_auth.consume_link_challenge(
                    session,
                    telegram_user_id=720000002,
                    chat_id=720000002,
                    code=challenge["code"],
                )

            stored_user = await session.get(User, user.id)
            assert stored_user is not None
            stored_user.auth_version += 1
            await session.commit()
            with pytest.raises(
                user_telegram_auth.UserTelegramAuthError,
                match="relink-required",
            ):
                await user_telegram_auth.resolve_linked_user(
                    session,
                    telegram_user_id=720000001,
                    chat_id=720000001,
                )
    finally:
        await _cleanup(organization.id, user.id)
