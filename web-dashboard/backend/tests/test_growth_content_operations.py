from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    GrowthContentItem,
    GrowthContentPublishSimulation,
    GrowthContentSchedule,
    GrowthSocialAccount,
    GrowthSocialProviderCapability,
    Organization,
    User,
)
from app.services import growth_content_operations as content_ops


def test_utm_generation_is_deterministic_and_preserves_existing_query() -> None:
    first = content_ops.add_utm_parameters(
        "https://example.com/landing?ref=abc",
        source="facebook",
        campaign="launch",
        content="variant-1",
    )
    second = content_ops.add_utm_parameters(
        "https://example.com/landing?ref=abc",
        source="facebook",
        campaign="launch",
        content="variant-1",
    )
    assert first == second
    assert first is not None
    assert "ref=abc" in first
    assert "utm_source=facebook" in first
    assert "utm_medium=social" in first
    assert "utm_campaign=launch" in first
    assert "utm_content=variant-1" in first


def test_invalid_links_and_non_opaque_media_refs_are_rejected() -> None:
    with pytest.raises(content_ops.GrowthContentError, match="invalid-link-url"):
        content_ops.add_utm_parameters(
            "javascript:alert(1)",
            source="x",
            campaign="test",
            content="variant",
        )
    with pytest.raises(
        content_ops.GrowthContentError, match="media-reference-must-be-opaque"
    ):
        content_ops.validate_media_refs(["https://example.com/image.png"])
    with pytest.raises(
        content_ops.GrowthContentError, match="media-reference-must-be-opaque"
    ):
        content_ops.validate_media_refs(["/tmp/private-image.png"])
    assert content_ops.validate_media_refs(
        ["studio:asset-1", "media:campaign/banner-v2", "asset:video-3"]
    ) == ["studio:asset-1", "media:campaign/banner-v2", "asset:video-3"]


def test_sensitive_content_metadata_is_rejected_recursively() -> None:
    with pytest.raises(
        content_ops.GrowthContentError, match="sensitive-field-rejected"
    ):
        content_ops._assert_safe_payload({"nested": {"access_token": "never-store"}})
    content_ops._assert_safe_payload(
        {"language": "ar", "campaign": {"audience": "business"}}
    )


def test_preview_never_claims_verified_limits_or_live_publish() -> None:
    content = SimpleNamespace(
        id="content-1",
        content_type="image",
        base_text="Base text",
        media_refs=["asset:image-1"],
        link_url="https://example.com",
    )
    variant = SimpleNamespace(
        id="variant-1",
        provider="instagram",
        account_id="account-1",
        text="Variant text",
        media_refs=["asset:image-2"],
        link_url="https://example.com",
        hashtags=["#launch"],
        mentions=["@brand"],
        platform_overrides={"placement": "feed"},
    )
    account = SimpleNamespace(account_kind="business")
    preview = content_ops.build_preview(
        content=content,  # type: ignore[arg-type]
        variant=variant,  # type: ignore[arg-type]
        account=account,  # type: ignore[arg-type]
    )
    assert preview["live_publish_allowed"] is False
    assert preview["provider_limits_verified"] is False
    assert preview["media_refs"] == ["asset:image-2"]
    assert preview["text"] == "Variant text"


@pytest.mark.asyncio
async def test_content_access_denial_fails_before_mutation(monkeypatch) -> None:
    async def denied(_session, _actor, _capability):
        return SimpleNamespace(
            allowed=False,
            reason="owner-deny",
            approval_required=True,
        )

    monkeypatch.setattr(content_ops.growth_access, "effective_access", denied)
    actor = SimpleNamespace(id="user", organization_id="org")
    with pytest.raises(
        content_ops.GrowthContentError, match="access-denied:owner-deny"
    ):
        await content_ops.create_content(  # type: ignore[arg-type]
            None,
            actor,
            {"title": "Denied", "content_type": "text"},
        )


@pytest.mark.asyncio
async def test_durable_content_workflow_approval_queue_recycle_and_simulation(
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs04-org-{suffix}"
    user_id = f"gs04-user-{suffix}"
    account_id = f"gs04-account-{suffix}"
    email = f"gs04-{suffix}@example.invalid"

    async def allow_with_approval(_session, _actor, _capability):
        return SimpleNamespace(
            allowed=True,
            reason="owner-grant",
            approval_required=True,
            limits={},
        )

    monkeypatch.setattr(
        content_ops.growth_access,
        "effective_access",
        allow_with_approval,
    )

    user_actor = UserRecord(
        id=user_id,
        email=email,
        name="GS04 Test User",
        role="User",
        password_hash="not-used",
        organization_id=org_id,
        organization_name="GS04 Test",
        organization_plan="test",
        permissions=[],
        status="active",
        auth_version=1,
    )
    owner_actor = UserRecord(
        id=user_id,
        email=email,
        name="GS04 Test Owner",
        role="Owner",
        password_hash="not-used",
        organization_id=org_id,
        organization_name="GS04 Test",
        organization_plan="test",
        permissions=[],
        status="active",
        auth_version=1,
    )

    async with SessionLocal() as session:
        try:
            session.add(
                Organization(
                    id=org_id,
                    name="GS04 Test",
                    slug=f"gs04-{suffix}",
                    plan="test",
                    status="active",
                )
            )
            session.add(
                User(
                    id=user_id,
                    organization_id=org_id,
                    email=email,
                    name="GS04 Test User",
                    password_hash="not-used",
                    status="active",
                    auth_version=1,
                )
            )
            await session.commit()
            account = GrowthSocialAccount(
                id=account_id,
                organization_id=org_id,
                created_by_id=user_id,
                provider="facebook",
                account_kind="page",
                external_account_id=f"page-{suffix}",
                display_name="GS04 Page",
                credential_ref="file:/run/operator-secrets/social/gs04-test-reference",
                status="active",
                health_state="healthy",
                health_reasons=["test-fixture"],
                provider_metadata={"test_fixture": True},
                settings={},
                version=1,
            )
            session.add(account)
            await session.commit()

            content = await content_ops.create_content(
                session,
                user_actor,
                {
                    "title": "Launch Campaign",
                    "content_type": "image",
                    "base_text": "A useful launch message",
                    "link_url": "https://example.com/offer?ref=gs04",
                    "media_refs": ["asset:launch-image-v1"],
                    "tags": ["launch", "growth"],
                    "content_metadata": {"language": "en"},
                },
            )
            variant = await content_ops.create_variant(
                session,
                user_actor,
                content.id,
                {
                    "provider": "facebook",
                    "account_id": account_id,
                    "text": "Facebook-specific launch copy",
                    "hashtags": ["#launch"],
                    "platform_overrides": {"placement": "feed"},
                },
            )
            preview = await content_ops.preview_variant(session, user_actor, variant.id)
            assert preview["live_publish_allowed"] is False
            assert preview["provider_limits_verified"] is False
            assert "utm_source=facebook" in preview["utm_url"]

            due = datetime.now(timezone.utc) - timedelta(minutes=1)
            with pytest.raises(
                content_ops.GrowthContentError, match="approval-required"
            ):
                await content_ops.schedule_variant(
                    session,
                    user_actor,
                    variant.id,
                    {
                        "scheduled_for": due,
                        "timezone": "UTC",
                        "recurrence": "daily",
                        "priority": 90,
                    },
                )

            requested = await content_ops.request_approval(
                session, user_actor, content.id
            )
            assert requested.approval_status == "pending"
            approved = await content_ops.decide_approval(
                session,
                owner_actor,
                content.id,
                approved=True,
                note="Approved for simulation",
            )
            assert approved.approval_status == "approved"

            schedule = await content_ops.schedule_variant(
                session,
                user_actor,
                variant.id,
                {
                    "scheduled_for": due,
                    "timezone": "UTC",
                    "recurrence": "daily",
                    "priority": 90,
                },
            )
            await session.commit()

            results = await content_ops.simulate_due_queue(
                session,
                user_actor,
                now=datetime.now(timezone.utc),
            )
            await session.commit()
            assert len(results) == 1
            result = results[0]
            assert result["status"] == "simulated_success"
            assert result["live_publish_allowed"] is False
            assert "simulation-only" in result["reason_codes"]
            assert "no-provider-call" in result["reason_codes"]
            assert "utm_source=facebook" in result["utm_url"]

            stored = await session.get(GrowthContentPublishSimulation, result["id"])
            assert stored is not None
            assert stored.live_publish_allowed is False

            recurrences = (
                await session.scalars(
                    select(GrowthContentSchedule).where(
                        GrowthContentSchedule.organization_id == org_id,
                        GrowthContentSchedule.recycle_of_schedule_id == schedule.id,
                    )
                )
            ).all()
            assert len(recurrences) == 1
            assert recurrences[0].status == "queued"
            assert recurrences[0].scheduled_for > schedule.scheduled_for

            stored_content = await session.get(GrowthContentItem, content.id)
            assert stored_content is not None
            assert stored_content.recycle_count == 1

            manual_recycle = await content_ops.recycle_schedule(
                session,
                user_actor,
                schedule.id,
                datetime.now(timezone.utc) + timedelta(days=14),
            )
            assert manual_recycle.recycle_of_schedule_id == schedule.id
            await session.commit()

            matrix = await session.scalar(
                select(GrowthSocialProviderCapability).where(
                    GrowthSocialProviderCapability.provider == "facebook",
                    GrowthSocialProviderCapability.capability == "content.publish",
                )
            )
            assert matrix is not None
            assert matrix.verification_state == "simulated"
            assert matrix.verified_at is None
            assert matrix.evidence["live_verified"] is False

            # Editing approved content invalidates approval immediately.
            changed = await content_ops.update_content(
                session,
                user_actor,
                content.id,
                {"base_text": "Changed after approval"},
            )
            assert changed.approval_status == "not_requested"
            assert changed.status == "draft"

            # Account interruption between scheduling and execution blocks the simulation.
            await content_ops.request_approval(session, user_actor, content.id)
            await content_ops.decide_approval(
                session,
                owner_actor,
                content.id,
                approved=True,
                note="Re-approved",
            )
            blocked_schedule = await content_ops.schedule_variant(
                session,
                user_actor,
                variant.id,
                {
                    "scheduled_for": datetime.now(timezone.utc) - timedelta(seconds=1),
                    "timezone": "UTC",
                    "recurrence": "none",
                    "priority": 100,
                },
            )
            queue = await content_ops.queue_snapshot(session, user_actor)
            assert queue[0]["id"] == blocked_schedule.id
            assert queue[0]["priority"] == 100
            account.status = "paused"
            account.health_state = "paused"
            account.health_reasons = ["test-pause"]
            await session.flush()
            blocked = await content_ops.simulate_schedule(
                session,
                user_actor,
                blocked_schedule.id,
                now=datetime.now(timezone.utc),
            )
            assert blocked.status == "simulated_blocked"
            assert blocked.live_publish_allowed is False
            assert "account-status:paused" in blocked.reason_codes
            await session.commit()
        finally:
            await session.rollback()
            org = await session.get(Organization, org_id)
            if org is not None:
                await session.delete(org)
            await session.commit()


def test_content_api_static_queue_route_precedes_dynamic_content_route() -> None:
    from app.api.v1.endpoints import growth_content

    paths = [getattr(route, "path", "") for route in growth_content.router.routes]
    assert "/queue" in paths
    assert "/{content_id}" in paths
    assert paths.index("/queue") < paths.index("/{content_id}")
