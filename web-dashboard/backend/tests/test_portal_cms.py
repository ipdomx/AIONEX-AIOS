"""Owner-controlled VIP portal configuration, publication, and asset contracts."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI, UploadFile
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from starlette.datastructures import Headers

from app.api.v1.router import api_router
from app.core.auth import UserRecord, require_super_owner
from app.core.config import settings
from app.db.base import SessionLocal
from app.db.models import AuditEvent, Organization, OwnerControlRecord, User
from app.services.portal_cms import (ASSET_DOMAIN, PORTAL_DOMAIN,
                                     PortalConfigurationError,
                                     default_portal_configuration,
                                     delete_portal_asset,
                                     ensure_portal_records,
                                     get_portal_snapshot, publish_portal_draft,
                                     replace_portal_draft,
                                     rollback_portal_publication,
                                     save_portal_asset,
                                     validate_portal_configuration)


def _owner() -> UserRecord:
    return UserRecord(
        id="phase27-owner",
        email="owner@aionex.local",
        name="AIONEX Owner",
        role="Super Owner",
        password_hash="unused",
        organization_id="aionex-org",
        organization_name="AIONEX",
        organization_plan="enterprise",
        permissions=["*"],
    )


async def _ensure_owner_identity() -> None:
    async with SessionLocal() as session:
        organization = await session.get(Organization, "aionex-org")
        if organization is None:
            session.add(
                Organization(
                    id="aionex-org",
                    name="AIONEX",
                    slug="aionex-phase27-test",
                    plan="enterprise",
                    status="active",
                )
            )
            await session.flush()
        user = await session.get(User, "phase27-owner")
        if user is None:
            session.add(
                User(
                    id="phase27-owner",
                    organization_id="aionex-org",
                    role_id=None,
                    email="phase27-owner@aionex.test",
                    name="AIONEX Owner",
                    password_hash="unused",
                    status="active",
                )
            )
        await session.commit()


async def _cleanup() -> None:
    async with SessionLocal() as session:
        await session.execute(
            delete(AuditEvent).where(
                AuditEvent.user_id == "phase27-owner",
                AuditEvent.action.like("owner.portal.%"),
            )
        )
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain.in_([PORTAL_DOMAIN, ASSET_DOMAIN])
            )
        )
        await session.execute(delete(User).where(User.id == "phase27-owner"))
        await session.execute(
            delete(Organization).where(Organization.id == "aionex-org")
        )
        await session.commit()


def test_default_configuration_covers_complete_owner_control_surface() -> None:
    configuration = validate_portal_configuration(default_portal_configuration())
    assert configuration["branding"]["logo_url"]
    assert configuration["theme"]["primary_color"].startswith("#")
    assert {item["id"] for item in configuration["navigation"]} >= {
        "home",
        "about",
        "pricing",
        "contact",
    }
    assert {"home", "about", "pricing", "contact"} <= set(configuration["pages"])
    assert configuration["pricing"]["enabled"] is True
    assert configuration["pricing"]["plans"][0]["id"] == "free"
    assert configuration["pricing"]["plans"][1]["enabled"] is False
    assert configuration["translation_overrides"] == {}


def test_configuration_rejects_executable_content_and_unsafe_urls() -> None:
    configuration = default_portal_configuration()
    configuration["pages"]["home"]["sections"][0]["content"]["description"] = {
        locale: "<script>alert(1)</script>"
        for locale in ("ar", "en", "fr", "de", "es", "tr")
    }
    with pytest.raises(PortalConfigurationError, match="executable content"):
        validate_portal_configuration(configuration)

    configuration = default_portal_configuration()
    configuration["branding"]["logo_url"] = "javascript:alert(1)"
    with pytest.raises(
        PortalConfigurationError, match="unsafe characters|root-relative or HTTPS"
    ):
        validate_portal_configuration(configuration)

    configuration = default_portal_configuration()
    configuration["custom_metadata"] = {"api_key": "sk-proj-not-public"}
    with pytest.raises(PortalConfigurationError, match="not a public portal field"):
        validate_portal_configuration(configuration)


@pytest.mark.asyncio
async def test_draft_publish_history_and_rollback_are_durable() -> None:
    await _cleanup()
    await _ensure_owner_identity()
    actor = _owner()
    try:
        async with SessionLocal() as session:
            draft, published = await ensure_portal_records(session)
            assert draft.resource_id == "draft"
            assert published.payload["publication"]["version"] == 1
            configuration = default_portal_configuration()
            configuration["branding"]["site_name"] = "AIONEX Controlled Portal"
            replaced = await replace_portal_draft(
                session,
                configuration,
                actor_id=actor.id,
                organization_id=actor.organization_id,
            )
            assert replaced["configuration"]["branding"]["site_name"] == (
                "AIONEX Controlled Portal"
            )
            first_publication = await publish_portal_draft(
                session,
                actor_id=actor.id,
                organization_id=actor.organization_id,
            )
            assert first_publication["publication"]["version"] == 2
            await session.commit()

        async with SessionLocal() as session:
            snapshot = await get_portal_snapshot(session)
            assert (
                snapshot["published"]["configuration"]["branding"]["site_name"]
                == "AIONEX Controlled Portal"
            )
            assert snapshot["history"][0]["version"] == 1
            rolled_back = await rollback_portal_publication(
                session,
                1,
                actor_id=actor.id,
                organization_id=actor.organization_id,
            )
            assert rolled_back["publication"]["version"] == 3
            assert rolled_back["configuration"]["branding"]["site_name"] == (
                "AIONEX AIOS"
            )
            await session.commit()

        async with SessionLocal() as session:
            actions = set(
                (
                    await session.scalars(
                        select(AuditEvent.action).where(
                            AuditEvent.user_id == actor.id,
                            AuditEvent.action.like("owner.portal.%"),
                        )
                    )
                ).all()
            )
            assert {
                "owner.portal.draft_updated",
                "owner.portal.published",
                "owner.portal.rolled_back",
            } <= actions
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_asset_upload_is_external_to_git_and_cannot_delete_referenced_asset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _cleanup()
    await _ensure_owner_identity()
    monkeypatch.setattr(settings, "PORTAL_ASSET_ROOT", str(tmp_path / "assets"))
    actor = _owner()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
    try:
        async with SessionLocal() as session:
            upload = UploadFile(
                filename="owner-logo.png",
                file=BytesIO(png),
                headers=Headers({"content-type": "image/png"}),
            )
            asset = await save_portal_asset(
                session,
                upload,
                actor_id=actor.id,
                organization_id=actor.organization_id,
            )
            assert asset["media_type"] == "image/png"
            assert Path(asset["path"]).is_file()
            configuration = default_portal_configuration()
            configuration["branding"]["logo_url"] = asset["public_url"]
            await replace_portal_draft(
                session,
                configuration,
                actor_id=actor.id,
                organization_id=actor.organization_id,
            )
            await session.commit()

        async with SessionLocal() as session:
            with pytest.raises(Exception) as exc_info:
                await delete_portal_asset(
                    session,
                    asset["asset_id"],
                    actor_id=actor.id,
                    organization_id=actor.organization_id,
                )
            assert getattr(exc_info.value, "status_code", None) == 409
            await session.rollback()
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_public_etag_and_owner_api_boundary() -> None:
    await _cleanup()
    await _ensure_owner_identity()
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[require_super_owner] = _owner
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            public = await client.get("/api/v1/portal/published")
            assert public.status_code == 200, public.text
            assert public.json()["configuration"]["pricing"]["plans"]
            etag = public.headers["etag"]
            cached = await client.get(
                "/api/v1/portal/published", headers={"If-None-Match": etag}
            )
            assert cached.status_code == 304
            owner = await client.get("/api/v1/owner/portal")
            assert owner.status_code == 200, owner.text
            assert owner.json()["published"]["publication"]["version"] == 1
    finally:
        app.dependency_overrides.clear()
        await _cleanup()
