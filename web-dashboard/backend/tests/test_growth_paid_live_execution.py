from __future__ import annotations

import hashlib
import io
import json
from datetime import timedelta
from types import SimpleNamespace
from urllib.error import URLError
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    GrowthControlledPilot,
    GrowthPaidLiveExecution,
    GrowthPaidLiveExecutionStep,
    GrowthSocialProviderCapability,
    Organization,
    User,
)
from app.services import growth_controlled_pilots as pilots
from app.services import growth_meta_live_execution_adapter as adapter
from app.services import growth_paid_campaigns as paid
from app.services import growth_paid_live_execution as execution
from app.services import growth_paid_live_plan as live_plan

ACCOUNT_ID = "123456789012345"
PAGE_ID = "623456789012345"
SCOPE_REF = (
    "accountref://meta/sha256/"
    + hashlib.sha256(
        f"meta-managed-ad-account:{ACCOUNT_ID}".encode("utf-8")
    ).hexdigest()
)
PAGE_REF = "pageref://meta/sha256/" + "a" * 64
PROVIDER_IDS = {
    "campaign": "223456789012345",
    "adset": "323456789012345",
    "creative": "423456789012345",
    "ad": "523456789012345",
}


@pytest_asyncio.fixture(autouse=True)
async def _isolate_live_execution_tests():
    async def cleanup() -> None:
        async with SessionLocal() as session:
            await session.execute(
                delete(GrowthSocialProviderCapability).where(
                    GrowthSocialProviderCapability.provider == "meta",
                    GrowthSocialProviderCapability.capability == "ads.manage",
                )
            )
            await session.execute(
                delete(Organization).where(Organization.slug.like("gs12-execution-%"))
            )
            await session.commit()

    await cleanup()
    yield
    await cleanup()


class FakeResponse(io.BytesIO):
    pass


def _response(payload: dict) -> FakeResponse:
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def _actor(org_id: str, user_id: str, role: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.invalid",
        name=role,
        role=role,
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS12 Execution",
        organization_plan="test",
        permissions=["*"] if role == "Super Owner" else [],
        status="active",
        auth_version=1,
    )


async def _fixture(session, monkeypatch):
    suffix = uuid4().hex[:10]
    org_id = str(uuid4())
    user_id = str(uuid4())
    owner_id = str(uuid4())
    user = _actor(org_id, user_id, "User")
    owner = _actor(org_id, owner_id, "Super Owner")

    async def allow(_session, _actor, _capability):
        return SimpleNamespace(allowed=True, reason="test-owner-grant")

    monkeypatch.setattr(paid.growth_access, "effective_access", allow)
    session.add(
        Organization(
            id=org_id,
            name="GS12 Execution",
            slug=f"gs12-execution-{suffix}",
            plan="test",
            status="active",
        )
    )
    session.add_all(
        [
            User(
                id=user_id,
                organization_id=org_id,
                email=user.email,
                name=user.name,
                password_hash="unused",
                status="active",
                auth_version=1,
            ),
            User(
                id=owner_id,
                organization_id=org_id,
                email=owner.email,
                name=owner.name,
                password_hash="unused",
                status="active",
                auth_version=1,
            ),
        ]
    )
    await session.flush()
    campaign = await paid.create_campaign(
        session,
        user,
        {
            "name": "Controlled Traffic",
            "objective": "traffic",
            "currency": "EUR",
            "total_budget_minor": 1500,
            "daily_budget_cap_minor": 400,
            "stop_loss_policy": {"max_cpa_minor": 250, "min_roas": 1.25},
            "metadata": {"prepared_by": "test"},
        },
    )
    ad_set = await paid.add_ad_set(
        session,
        user,
        campaign.id,
        {
            "name": "Instagram AE",
            "provider": "instagram",
            "audience": {"countries": ["AE"]},
            "placements": ["feed"],
            "bid_strategy": "lowest_cost",
            "daily_budget_cap_minor": 400,
        },
    )
    creative = await paid.add_creative(
        session,
        user,
        campaign.id,
        {
            "name": "Traffic Creative",
            "format": "image",
            "headline": "Visit AIONEX",
            "body": "Learn more",
            "destination_url": "https://example.invalid/offer",
            "utm": {"utm_source": "aios"},
        },
    )
    ad = await paid.add_ad(
        session,
        user,
        campaign.id,
        {"name": "Traffic Ad", "ad_set_id": ad_set.id, "creative_id": creative.id},
    )
    await paid.approve_campaign(session, owner, campaign.id)
    pilot = GrowthControlledPilot(
        id=str(uuid4()),
        organization_id=org_id,
        created_by_id=owner_id,
        provider="meta",
        provider_scope="managed_ad_account",
        scope_ref=SCOPE_REF,
        mode="live_spend",
        capability="ads.manage",
        status="armed",
        owner_approved_by_id=owner_id,
        owner_approved_at=pilots._now(),
        owner_approval_reference="test-owner-approval",
        legal_policy_acknowledged=True,
        legal_policy_reference="test-legal-policy",
        legal_acknowledged_by_id=owner_id,
        legal_acknowledged_at=pilots._now(),
        launch_authorized=True,
        launch_authorized_by_id=owner_id,
        launch_authorized_at=pilots._now(),
        currency="EUR",
        max_total_budget_minor=2000,
        max_daily_budget_minor=500,
        max_cpa_minor=300,
        min_roas=1.5,
        expires_at=pilots._now() + timedelta(hours=24),
        armed_at=pilots._now(),
        live_provider_mutation_allowed=True,
        real_spend_allowed=True,
        evidence={},
        blocked_reasons=[],
        version=1,
    )
    session.add(pilot)
    capability = await session.scalar(
        select(GrowthSocialProviderCapability).where(
            GrowthSocialProviderCapability.provider == "meta",
            GrowthSocialProviderCapability.capability == "ads.manage",
        )
    )
    if capability is None:
        capability = GrowthSocialProviderCapability(
            provider="meta",
            capability="ads.manage",
            verification_state="live_write_verified",
            mutation_class="write",
            evidence={},
            verified_at=pilots._now(),
            version=1,
        )
        session.add(capability)
    capability.verification_state = "live_write_verified"
    capability.mutation_class = "write"
    capability.evidence = {
        "mutation_allowed": True,
        "spend_allowed": False,
        "live_no_spend_write_verified": True,
        "live_scope_ref": SCOPE_REF,
        "live_organization_id": org_id,
        "execution_adapter_verified": True,
        "execution_adapter_scope_ref": SCOPE_REF,
        "execution_adapter_organization_id": org_id,
    }
    capability.verified_at = pilots._now()
    await session.flush()
    prepared = await live_plan.prepare_live_plan(
        session,
        owner,
        campaign.id,
        pilot.id,
        creative_identity_ref=PAGE_REF,
    )
    assert prepared["plan_compilable"] is True
    await session.commit()
    return owner, campaign, ad_set, creative, ad, pilot


def _patch_resolution(monkeypatch):
    monkeypatch.setattr(
        execution.targets,
        "resolve_scope_ref_to_raw_id",
        lambda _scope_ref, opener=None: (
            ACCOUNT_ID,
            {
                "currency": "EUR",
                "timezone_name": "Asia/Nicosia",
                "ads_management": True,
                "provider_write_executed": False,
                "provider_spend_executed": False,
            },
        ),
    )
    monkeypatch.setattr(
        execution.pages,
        "resolve_page_ref_to_raw_id",
        lambda _page_ref, opener=None: (PAGE_ID, ["ADVERTISE"]),
    )
    monkeypatch.setattr(
        adapter.meta_owned, "_safe_config", lambda: ("/run/fake", "v26.0")
    )
    monkeypatch.setattr(
        adapter.meta_owned, "_read_token", lambda _path: "fake-meta-token"
    )


def _provider_opener(request, timeout=20):
    assert timeout == 20
    url = request.full_url
    method = request.get_method()
    if method == "GET" and "fields=id,account_id" in url:
        object_id = url.rsplit("/", 1)[-1].split("?", 1)[0]
        return _response({"id": object_id, "account_id": f"act_{ACCOUNT_ID}"})
    if method != "POST":
        raise AssertionError(f"unexpected provider method: {method}")
    if url.endswith(f"/act_{ACCOUNT_ID}/campaigns"):
        return _response({"id": PROVIDER_IDS["campaign"]})
    if url.endswith(f"/act_{ACCOUNT_ID}/adsets"):
        return _response({"id": PROVIDER_IDS["adset"]})
    if url.endswith(f"/act_{ACCOUNT_ID}/adcreatives"):
        return _response({"id": PROVIDER_IDS["creative"]})
    if url.endswith(f"/act_{ACCOUNT_ID}/ads"):
        return _response({"id": PROVIDER_IDS["ad"]})
    raise AssertionError(f"unexpected provider URL: {url}")


@pytest.mark.asyncio
async def test_prepare_execution_is_durable_no_provider_call_and_no_raw_ids(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, campaign, _, _, _, _ = await _fixture(session, monkeypatch)
        result = await execution.prepare_execution(session, owner, campaign.id)
        await session.commit()
        assert result["status"] == "prepared"
        assert result["provider_write_calls_completed"] == 0
        assert result["spend_executed"] is False
        assert result["automatic_execution_allowed"] is False
        assert result["raw_provider_object_ids_returned"] is False
        assert [step["resource_kind"] for step in result["steps"]] == [
            "campaign",
            "ad_set",
            "creative",
            "ad",
        ]
        assert all(step["provider_object_ref"] is None for step in result["steps"])
        assert not any(value in json.dumps(result) for value in PROVIDER_IDS.values())


@pytest.mark.asyncio
async def test_execute_paused_plan_uses_guarded_adapter_once_per_step_and_is_idempotent(
    monkeypatch,
) -> None:
    _patch_resolution(monkeypatch)
    calls: list[str] = []

    def opener(request, timeout=20):
        calls.append(request.get_method() + " " + request.full_url)
        return _provider_opener(request, timeout=timeout)

    async with SessionLocal() as session:
        owner, campaign, _, _, _, pilot = await _fixture(session, monkeypatch)
        prepared = await execution.prepare_execution(session, owner, campaign.id)
        await session.commit()
        result = await execution.execute_paused_plan(
            session,
            owner,
            campaign.id,
            prepared["id"],
            plan_digest=prepared["plan_digest"],
            confirmation=execution.EXECUTE_CONFIRMATION,
            provider_opener=opener,
        )
        assert result["status"] == "paused_ready"
        assert result["provider_write_calls_completed"] == 4
        assert result["spend_executed"] is False
        assert result["automatic_execution_allowed"] is False
        assert all(step["status"] == "succeeded" for step in result["steps"])
        assert all(step["provider_object_ref"] for step in result["steps"])
        serialized = json.dumps(result, sort_keys=True)
        assert not any(value in serialized for value in PROVIDER_IDS.values())
        assert sum(1 for call in calls if call.startswith("POST ")) == 4

        repeated_call_count = len(calls)
        repeated = await execution.execute_paused_plan(
            session,
            owner,
            campaign.id,
            prepared["id"],
            plan_digest=prepared["plan_digest"],
            confirmation=execution.EXECUTE_CONFIRMATION,
            provider_opener=opener,
        )
        assert repeated["status"] == "paused_ready"
        assert len(calls) == repeated_call_count
        await session.refresh(campaign)
        await session.refresh(pilot)
        assert campaign.status == "live_paused"
        assert campaign.live_provider_call is True
        assert campaign.live_campaign_mutation is True
        assert campaign.real_spend_allowed is False
        assert pilot.status == "armed"
        assert pilot.real_spend_allowed is True


@pytest.mark.asyncio
async def test_ambiguous_provider_failure_never_retries_and_auto_disarms_pilot(
    monkeypatch,
) -> None:
    _patch_resolution(monkeypatch)
    post_calls = 0

    def failing_opener(request, timeout=20):
        nonlocal post_calls
        if request.get_method() == "POST":
            post_calls += 1
            raise URLError("synthetic transport loss")
        return _provider_opener(request, timeout=timeout)

    async with SessionLocal() as session:
        owner, campaign, _, _, _, pilot = await _fixture(session, monkeypatch)
        campaign_id = campaign.id
        prepared = await execution.prepare_execution(session, owner, campaign_id)
        await session.commit()
        with pytest.raises(
            execution.GrowthPaidLiveExecutionError,
            match="live-execution-step-manual-review",
        ):
            await execution.execute_paused_plan(
                session,
                owner,
                campaign_id,
                prepared["id"],
                plan_digest=prepared["plan_digest"],
                confirmation=execution.EXECUTE_CONFIRMATION,
                provider_opener=failing_opener,
            )
        assert post_calls == 1
        row = await session.get(GrowthPaidLiveExecution, prepared["id"])
        await session.refresh(pilot)
        assert row is not None
        assert row.status == "manual_review"
        assert row.manual_review_required is True
        assert pilot.status == "auto_disarmed"
        assert pilot.launch_authorized is False
        assert pilot.live_provider_mutation_allowed is False
        assert pilot.real_spend_allowed is False
        with pytest.raises(
            execution.GrowthPaidLiveExecutionError,
            match="live-execution-manual-review-required",
        ):
            await execution.execute_paused_plan(
                session,
                owner,
                campaign_id,
                prepared["id"],
                plan_digest=prepared["plan_digest"],
                confirmation=execution.EXECUTE_CONFIRMATION,
                provider_opener=failing_opener,
            )
        assert post_calls == 1


@pytest.mark.asyncio
async def test_stale_executing_step_is_manual_review_and_pilot_is_auto_disarmed(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, campaign, _, _, _, pilot = await _fixture(session, monkeypatch)
        prepared = await execution.prepare_execution(session, owner, campaign.id)
        await session.commit()
        step = await session.scalar(
            select(GrowthPaidLiveExecutionStep)
            .where(GrowthPaidLiveExecutionStep.execution_id == prepared["id"])
            .order_by(GrowthPaidLiveExecutionStep.step_order)
        )
        assert step is not None
        step.status = "executing"
        step.attempt_count = 1
        step.provider_call_started_at = execution._now() - timedelta(minutes=5)
        await session.commit()
        result = await execution.reconcile_stale_live_executions(
            session, stale_seconds=30
        )
        await session.commit()
        assert result == {
            "stale_steps": 1,
            "executions_marked_manual_review": 1,
            "pilots_auto_disarmed": 1,
        }
        row = await session.get(GrowthPaidLiveExecution, prepared["id"])
        await session.refresh(pilot)
        assert row is not None and row.status == "manual_review"
        assert pilot.status == "auto_disarmed"
        assert pilot.real_spend_allowed is False


def test_live_execution_confirmation_and_targeting_are_fail_closed() -> None:
    assert execution.EXECUTE_CONFIRMATION == "EXECUTE PAUSED META PLAN"
    ad_set = SimpleNamespace(
        provider="instagram",
        audience={"countries": ["AE"]},
        placements=["feed", "stories"],
        bid_strategy="lowest_cost",
    )
    assert execution._meta_targeting(ad_set) == {
        "geo_locations": {"countries": ["AE"]},
        "publisher_platforms": ["instagram"],
        "instagram_positions": ["stream", "story"],
    }
    with pytest.raises(
        execution.GrowthPaidLiveExecutionError, match="live-placement-not-supported"
    ):
        execution._meta_targeting(
            SimpleNamespace(
                provider="instagram",
                audience={"countries": ["AE"]},
                placements=["unknown-placement"],
                bid_strategy="lowest_cost",
            )
        )
