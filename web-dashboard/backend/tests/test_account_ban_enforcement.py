"""Permanent account-ban enforcement across durable AIOS identity signals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.core.auth import auth_service, pwd_context
from app.db.base import SessionLocal
from app.db.models import (
    ExternalIdentity,
    Organization,
    OwnerControlRecord,
    RefreshSession,
    Role,
    User,
)
from app.services import account_bans


@pytest.mark.asyncio
async def test_account_ban_revokes_sessions_blocks_known_identity_re_registration_and_can_be_owner_restored() -> None:
    suffix = uuid4().hex[:12]
    organization = Organization(
        name=f"Ban Enforcement {suffix}",
        slug=f"ban-enforcement-{suffix}",
        plan="free",
        status="active",
    )
    target_id: str | None = None
    second_id: str | None = None
    try:
        async with SessionLocal() as session:
            session.add(organization)
            await session.flush()
            owner_role = Role(
                organization_id=organization.id,
                name="Super Owner",
                status="active",
            )
            user_role = Role(
                organization_id=organization.id,
                name="Free User",
                status="active",
            )
            session.add_all([owner_role, user_role])
            await session.flush()
            owner = User(
                organization_id=organization.id,
                role_id=owner_role.id,
                email=f"ban-owner-{suffix}@example.com",
                name="Ban Test Owner",
                password_hash=pwd_context.hash(f"BanOwner!{suffix}Aa1"),
                status="active",
            )
            target = User(
                organization_id=organization.id,
                role_id=user_role.id,
                email=f"banned-{suffix}@example.com",
                name="Ban Target",
                password_hash=pwd_context.hash(f"BanTarget!{suffix}Aa1"),
                status="active",
            )
            session.add_all([owner, target])
            await session.flush()
            target_id = target.id

            username = f"banned_{suffix}"
            phone_hash = account_bans.identity_hmac(f"+97150{suffix[:7]}")
            firebase_hash = account_bans.identity_hmac(f"firebase-{suffix}")
            network_hash = account_bans.identity_hmac(f"network-{suffix}")
            device_hash = account_bans.identity_hmac(f"device-{suffix}")
            session.add(
                OwnerControlRecord(
                    domain=account_bans.REGISTRATION_TELEMETRY_DOMAIN,
                    resource_id=target.id,
                    status="active",
                    enabled=True,
                    payload={
                        "username": username,
                        "phone_hash": phone_hash,
                        "network_hash": network_hash,
                        "device_hash": device_hash,
                        "phone_verification": {
                            "firebase_uid_hash": firebase_hash,
                        },
                    },
                )
            )
            session.add(
                ExternalIdentity(
                    user_id=target.id,
                    provider="google",
                    subject=f"subject-{suffix}",
                    email=target.email,
                    provider_metadata={"firebase_uid": f"social-firebase-{suffix}"},
                )
            )
            refresh = RefreshSession(
                user_id=target.id,
                token_hash=f"{suffix:0<64}"[:64],
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
            session.add(refresh)
            await session.flush()

            starting_auth_version = target.auth_version
            signals = await account_bans.ban_user(
                session,
                user=target,
                actor_id=owner.id,
                reason="Repeated abusive use",
            )
            await session.commit()
            await session.refresh(target)
            await session.refresh(refresh)

            assert signals >= 8
            assert target.status == "banned"
            assert target.auth_version == starting_auth_version + 1
            assert refresh.revoked_at is not None

            with pytest.raises(HTTPException) as auth_error:
                await auth_service.get_user_by_id(session, target.id)
            assert auth_error.value.status_code == 403

            checks = [
                {"email": target.email},
                {"username": username},
                {"phone_hash": phone_hash},
                {"firebase_uid_hash": firebase_hash},
                {"network_hash": network_hash},
                {"device_hash": device_hash},
                {
                    "social_provider": "google",
                    "social_subject": f"subject-{suffix}",
                },
                {"social_firebase_uid": f"social-firebase-{suffix}"},
            ]
            for kwargs in checks:
                with pytest.raises(HTTPException) as blocked:
                    await account_bans.assert_registration_not_banned(
                        session, **kwargs
                    )
                assert blocked.value.status_code == 403
                assert blocked.value.detail["code"] == "ACCOUNT_BANNED"

            active_bans = list(
                (
                    await session.scalars(
                        select(OwnerControlRecord).where(
                            OwnerControlRecord.domain.in_(
                                tuple(account_bans.BAN_DOMAINS)
                            ),
                            OwnerControlRecord.enabled.is_(True),
                            OwnerControlRecord.status == "banned",
                        )
                    )
                ).all()
            )
            assert len(active_bans) >= 8
            serialized = str([item.payload for item in active_bans])
            assert target.email not in serialized
            assert f"subject-{suffix}" not in serialized

            released = await account_bans.unban_user(
                session, user=target, actor_id=owner.id
            )
            await session.commit()
            await session.refresh(target)
            assert released >= 8
            assert target.status == "active"
            await account_bans.assert_registration_not_banned(
                session,
                email=target.email,
                phone_hash=phone_hash,
                network_hash=network_hash,
                device_hash=device_hash,
            )

            # A later ban on a shared exact signal must not silently re-add the
            # restored user to that ban record.
            second = User(
                organization_id=organization.id,
                role_id=user_role.id,
                email=f"banned-second-{suffix}@example.com",
                name="Second Ban Target",
                password_hash=pwd_context.hash(f"BanSecond!{suffix}Aa1"),
                status="active",
            )
            session.add(second)
            await session.flush()
            second_id = second.id
            session.add(
                OwnerControlRecord(
                    domain=account_bans.REGISTRATION_TELEMETRY_DOMAIN,
                    resource_id=second.id,
                    status="active",
                    enabled=True,
                    payload={
                        "username": f"banned_second_{suffix}",
                        "network_hash": network_hash,
                    },
                )
            )
            await session.flush()
            await account_bans.ban_user(
                session,
                user=second,
                actor_id=owner.id,
                reason="Shared signal membership validation",
            )
            await session.commit()
            network_record = await session.scalar(
                select(OwnerControlRecord).where(
                    OwnerControlRecord.domain == account_bans.ACCOUNT_BAN_NETWORK_DOMAIN,
                    OwnerControlRecord.resource_id == network_hash,
                )
            )
            assert network_record is not None
            assert target.id not in set(network_record.payload.get("user_ids", []))
            assert second.id in set(network_record.payload.get("user_ids", []))
            with pytest.raises(HTTPException) as shared_block:
                await account_bans.assert_registration_not_banned(
                    session, network_hash=network_hash
                )
            assert shared_block.value.status_code == 403
            await account_bans.unban_user(
                session, user=second, actor_id=owner.id
            )
            await session.commit()
            await account_bans.assert_registration_not_banned(
                session, network_hash=network_hash
            )
    finally:
        async with SessionLocal() as session:
            cleanup_user_ids = [
                item for item in (target_id, second_id) if item is not None
            ]
            if cleanup_user_ids:
                await session.execute(
                    delete(OwnerControlRecord).where(
                        OwnerControlRecord.domain == account_bans.REGISTRATION_TELEMETRY_DOMAIN,
                        OwnerControlRecord.resource_id.in_(cleanup_user_ids),
                    )
                )
                await session.execute(
                    delete(OwnerControlRecord).where(
                        OwnerControlRecord.domain.in_(tuple(account_bans.BAN_DOMAINS)),
                        OwnerControlRecord.payload["user_id"].as_string().in_(
                            cleanup_user_ids
                        ),
                    )
                )
            stored = await session.get(Organization, organization.id)
            if stored is not None:
                await session.delete(stored)
            await session.commit()
