"""Phase 36M unified Studio governance contracts."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.api.owner import studio_governance as owner_studio_routes
from app.api.v1.endpoints import studio as studio_routes
from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import Organization, OwnerControlRecord, User
from app.services import studio_governance


def actor(
    *,
    plan: str = "enterprise",
    org: str | None = None,
    permissions: list[str] | None = None,
) -> UserRecord:
    suffix = uuid4().hex[:8]
    return UserRecord(
        id=f"studio-user-{suffix}",
        email=f"studio-{suffix}@example.invalid",
        name="Studio User",
        role="Owner",
        password_hash="unused",
        organization_id=org or f"studio-org-{suffix}",
        organization_name="Studio Org",
        organization_plan=plan,
        permissions=list(permissions if permissions is not None else ["*"]),
    )


def test_catalog_covers_unified_product_families_and_departments_once() -> None:
    ids = {item.capability_id for item in studio_governance.CAPABILITIES}
    assert {
        "software",
        "prompt-text",
        "design-image",
        "audio",
        "video-motion",
        "three-d-xr",
        "music-song",
        "courses",
        "sector-solutions",
        "realtime",
    } <= ids
    departments = [
        department
        for item in studio_governance.CAPABILITIES
        for department in item.departments
    ]
    assert len(departments) == len(set(departments)) == 12


def test_course_family_requires_read_permission_but_not_write_permission_to_be_discoverable() -> (
    None
):
    definition = next(
        item
        for item in studio_governance.CAPABILITIES
        if item.capability_id == "courses"
    )
    assert definition.launch_surface == "academy"
    assert definition.supported_plans == ("starter", "professional", "enterprise")
    assert definition.required_permissions == ("academy:read",)


def test_provider_neutral_policy_rejects_external_cost_or_unknown_plan() -> None:
    definition = next(
        item
        for item in studio_governance.CAPABILITIES
        if item.capability_id == "design-image"
    )
    with pytest.raises(
        studio_governance.StudioGovernanceError, match="zero external cost"
    ):
        studio_governance.normalize_policy(
            definition, {"max_cost_usd": 0.01}, enabled=True
        )
    with pytest.raises(studio_governance.StudioGovernanceError, match="unknown plan"):
        studio_governance.normalize_policy(
            definition, {"eligible_plans": ["enterprise", "secret-plan"]}, enabled=True
        )


@pytest.mark.asyncio
async def test_owner_policy_is_durable_and_studio_admission_fails_closed_when_disabled() -> (
    None
):
    owner = actor()
    async with SessionLocal() as session:
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain == studio_governance.POLICY_DOMAIN
            )
        )
        session.add(
            Organization(
                id=owner.organization_id,
                name=owner.organization_name,
                slug=owner.organization_id,
                plan=owner.organization_plan,
                status="active",
            )
        )
        session.add(
            User(
                id=owner.id,
                organization_id=owner.organization_id,
                role_id=None,
                email=owner.email,
                name=owner.name,
                password_hash="unused",
                status="active",
            )
        )
        await session.commit()
        result = await studio_governance.update_policy(
            session,
            actor=owner,
            capability_id="design-image",
            enabled=False,
            payload={
                "eligible_plans": ["free", "starter", "professional", "enterprise"],
                "daily_job_limit": 10,
                "max_concurrent_jobs": 2,
                "max_attempts": 2,
                "max_cost_usd": 0,
                "provider_mode": "provider_neutral",
                "moderation_mode": "strict",
            },
        )
        await session.commit()
        assert result["policy"]["enabled"] is False
        with pytest.raises(
            studio_governance.StudioGovernanceError, match="disabled by the Owner"
        ):
            await studio_governance.admit_studio_job(session, owner, "image")
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain == studio_governance.POLICY_DOMAIN
            )
        )
        await session.execute(
            delete(Organization).where(Organization.id == owner.organization_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_user_catalog_applies_plan_eligibility_without_writing_defaults() -> None:
    owner = actor(plan="enterprise")
    async with SessionLocal() as session:
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain == studio_governance.POLICY_DOMAIN
            )
        )
        session.add(
            OwnerControlRecord(
                domain=studio_governance.POLICY_DOMAIN,
                resource_id="software",
                status="active",
                enabled=True,
                payload={
                    "eligible_plans": ["enterprise"],
                    "daily_job_limit": 20,
                    "max_concurrent_jobs": 3,
                    "max_attempts": 3,
                    "max_cost_usd": 0,
                    "provider_mode": "provider_neutral",
                    "moderation_mode": "standard",
                },
            )
        )
        await session.commit()
        enterprise = await studio_governance.user_catalog(session, owner)
        free = await studio_governance.user_catalog(
            session, actor(plan="free", org=owner.organization_id)
        )
        enterprise_software = next(
            item for item in enterprise if item["capability_id"] == "software"
        )
        free_software = next(
            item for item in free if item["capability_id"] == "software"
        )
        assert enterprise_software["available"] is True
        assert free_software["available"] is False
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain == studio_governance.POLICY_DOMAIN
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_course_factory_user_catalog_requires_academy_read_permission() -> (
    None
):
    organization_id = f"studio-org-{uuid4().hex[:8]}"
    denied = actor(
        plan="enterprise",
        org=organization_id,
        permissions=["projects:read", "projects:write"],
    )
    allowed = actor(
        plan="enterprise",
        org=organization_id,
        permissions=["academy:read"],
    )
    async with SessionLocal() as session:
        denied_catalog = await studio_governance.user_catalog(session, denied)
        denied_courses = next(
            item for item in denied_catalog if item["capability_id"] == "courses"
        )
        assert denied_courses["available"] is False
        assert denied_courses["availability_reason"] == "permission_required"
        assert denied_courses["required_permissions"] == ["academy:read"]

        allowed_catalog = await studio_governance.user_catalog(session, allowed)
        allowed_courses = next(
            item for item in allowed_catalog if item["capability_id"] == "courses"
        )
        assert allowed_courses["available"] is True
        assert allowed_courses["availability_reason"] == "available"


def test_phase36m_routes_are_registered() -> None:
    studio_paths = {
        str(getattr(route, "path", "")) for route in studio_routes.router.routes
    }
    owner_paths = {
        str(getattr(route, "path", "")) for route in owner_studio_routes.router.routes
    }
    assert "/hub" in studio_paths
    assert "/owner/studio-governance" in owner_paths
    assert "/owner/studio-governance/{capability_id}" in owner_paths
