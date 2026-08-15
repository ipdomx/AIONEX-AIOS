from __future__ import annotations

from uuid import uuid4

import pytest
from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import Organization, OwnerControlRecord, User
from app.services import growth_access


def _owner(
    org_id: str, user_id: str, email: str, role: str = "Super Owner"
) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=email,
        name="Growth Access Owner",
        role=role,
        password_hash="unused",
        organization_id=org_id,
        organization_name="Growth Access Test",
        organization_plan="test",
        permissions=["*"],
        status="active",
        auth_version=1,
    )


async def _fixtures(session):
    suffix = uuid4().hex[:10]
    org_id = f"growth-access-org-{suffix}"
    owner_id = f"growth-access-owner-{suffix}"
    target_id = f"growth-access-user-{suffix}"
    owner = _owner(org_id, owner_id, f"owner-{suffix}@example.invalid")
    session.add(
        Organization(
            id=org_id,
            name="Growth Access Test",
            slug=f"growth-access-{suffix}",
            plan="test",
            status="active",
        )
    )
    await session.flush()
    session.add_all(
        [
            User(
                id=owner_id,
                organization_id=org_id,
                email=owner.email,
                name=owner.name,
                password_hash="unused",
                status="active",
                auth_version=1,
            ),
            User(
                id=target_id,
                organization_id=org_id,
                email=f"target-{suffix}@example.invalid",
                name="Growth Target User",
                password_hash="unused",
                status="active",
                auth_version=1,
            ),
        ]
    )
    await session.flush()
    return owner, org_id, target_id


@pytest.mark.asyncio
async def test_owner_override_listing_is_enriched_and_fail_closed() -> None:
    async with SessionLocal() as session:
        owner, _org_id, target_id = await _fixtures(session)
        decision = await growth_access.set_owner_override(
            session,
            owner,
            scope="user",
            subject_id=target_id,
            capability="ads.manage",
            allowed=True,
            approval_required=True,
            limits={"monthly_campaigns": 2, "regions": ["AE"]},
        )
        assert decision.allowed is True
        assert decision.limits == {"monthly_campaigns": 2, "regions": ["AE"]}

        snapshot = await growth_access.list_owner_overrides(session, owner)
        assert snapshot["provider_write_executed"] is False
        assert snapshot["provider_spend_executed"] is False
        assert snapshot["raw_credentials_returned"] is False
        assert snapshot["invalid_records"] == 0
        assert len(snapshot["items"]) == 1
        item = snapshot["items"][0]
        assert item["scope"] == "user"
        assert item["subject_id"] == target_id
        assert item["subject_name"] == "Growth Target User"
        assert item["subject_detail"].endswith("@example.invalid")
        assert item["subject_status"] == "active"
        assert item["capability"] == "ads.manage"
        assert item["allowed"] is True
        assert item["approval_required"] is True
        assert item["limits"] == {"monthly_campaigns": 2, "regions": ["AE"]}
        assert item["limits_redacted"] is False

        cleared = await growth_access.clear_owner_override(
            session,
            owner,
            scope="user",
            subject_id=target_id,
            capability="ads.manage",
        )
        assert cleared is True
        assert (await growth_access.list_owner_overrides(session, owner))["items"] == []
        await session.rollback()


@pytest.mark.asyncio
async def test_owner_override_rejects_missing_subject_and_raw_credentials() -> None:
    async with SessionLocal() as session:
        owner, _org_id, target_id = await _fixtures(session)

        with pytest.raises(ValueError, match="subject-not-found"):
            await growth_access.set_owner_override(
                session,
                owner,
                scope="user",
                subject_id="missing-user",
                capability="analytics.read",
                allowed=True,
            )

        with pytest.raises(ValueError, match="credential-material-forbidden-in-limits"):
            await growth_access.set_owner_override(
                session,
                owner,
                scope="user",
                subject_id=target_id,
                capability="analytics.read",
                allowed=True,
                limits={"access_token": "must-never-persist"},
            )

        with pytest.raises(ValueError, match="credential-material-forbidden-in-limits"):
            await growth_access.set_owner_override(
                session,
                owner,
                scope="user",
                subject_id=target_id,
                capability="analytics.read",
                allowed=True,
                limits={"header": "Bearer definitely-not-a-real-token"},
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_owner_override_listing_redacts_unsafe_legacy_limits() -> None:
    async with SessionLocal() as session:
        owner, _org_id, target_id = await _fixtures(session)
        resource_id = growth_access._resource_id("user", target_id, "analytics.read")
        session.add(
            OwnerControlRecord(
                domain=growth_access.OVERRIDE_DOMAIN,
                resource_id=resource_id,
                status="active",
                enabled=True,
                payload={
                    "scope": "user",
                    "subject_id": target_id,
                    "capability": "analytics.read",
                    "allowed": True,
                    "approval_required": False,
                    "limits": {"secret": "legacy-unsafe-value"},
                },
                version=1,
            )
        )
        await session.flush()
        snapshot = await growth_access.list_owner_overrides(session, owner)
        assert len(snapshot["items"]) == 1
        item = snapshot["items"][0]
        assert item["limits"] == {}
        assert item["limits_redacted"] is True
        assert "legacy-unsafe-value" not in repr(snapshot)
        await session.rollback()


@pytest.mark.asyncio
async def test_non_super_owner_cannot_manage_growth_access_overrides() -> None:
    async with SessionLocal() as session:
        owner, _org_id, target_id = await _fixtures(session)
        ordinary_owner = _owner(
            owner.organization_id,
            owner.id,
            owner.email,
            role="Owner",
        )
        with pytest.raises(ValueError, match="super-owner-required"):
            await growth_access.set_owner_override(
                session,
                ordinary_owner,
                scope="user",
                subject_id=target_id,
                capability="analytics.read",
                allowed=True,
            )
        with pytest.raises(ValueError, match="super-owner-required"):
            await growth_access.list_owner_overrides(session, ordinary_owner)
        await session.rollback()
