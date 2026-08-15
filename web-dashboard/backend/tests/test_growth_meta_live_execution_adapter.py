from __future__ import annotations

import io
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import GrowthSocialProviderCapability, Organization, User
from app.services import growth_controlled_pilots as pilots
from app.services import growth_meta_live_execution_adapter as adapter
from app.services import growth_meta_owned_write as owned_write

ACCOUNT_ID = "123456789012345"
SCOPE_REF = owned_write.opaque_scope_ref(ACCOUNT_ID)


def _actor(org_id: str, user_id: str) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=f"{user_id}@example.invalid",
        name="GS12 Adapter Owner",
        role="Super Owner",
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS12 Adapter",
        organization_plan="test",
        permissions=["*"],
        status="active",
        auth_version=1,
    )


async def _fixture(session, *, ready_controls: bool = False):
    suffix = uuid4().hex[:10]
    org_id = f"gs12-adapter-org-{suffix}"
    owner_id = f"gs12-adapter-owner-{suffix}"
    owner = _actor(org_id, owner_id)
    session.add(
        Organization(
            id=org_id,
            name="GS12 Adapter",
            slug=f"gs12-adapter-{suffix}",
            plan="test",
            status="active",
        )
    )
    await session.flush()
    session.add(
        User(
            id=owner_id,
            organization_id=org_id,
            email=owner.email,
            name=owner.name,
            password_hash="unused",
            status="active",
            auth_version=1,
        )
    )
    await session.flush()
    cap = await session.scalar(
        select(GrowthSocialProviderCapability).where(
            GrowthSocialProviderCapability.provider == "meta",
            GrowthSocialProviderCapability.capability == "ads.manage",
        )
    )
    evidence = {
        "mutation_allowed": True,
        "spend_allowed": False,
        "live_no_spend_write_verified": True,
        "execution_adapter_verified": False,
        "live_scope_ref": SCOPE_REF,
        "live_organization_id": org_id,
    }
    if cap is None:
        cap = GrowthSocialProviderCapability(
            provider="meta",
            capability="ads.manage",
            verification_state="live_write_verified",
            mutation_class="write",
            evidence=evidence,
            version=1,
        )
        session.add(cap)
    else:
        cap.verification_state = "live_write_verified"
        cap.mutation_class = "write"
        cap.evidence = evidence
        cap.version += 1
    await session.flush()
    pilot = await pilots.create_pilot(
        session,
        owner,
        {
            "organization_id": org_id,
            "provider": "meta",
            "provider_scope": "managed_ad_account",
            "scope_ref": SCOPE_REF,
            "mode": "live_spend",
            "owner_approval_reference": "gs12-adapter-test-approval",
        },
    )
    if ready_controls:
        await pilots.configure_controls(
            session,
            owner,
            pilot.id,
            {
                "legal_policy_acknowledged": True,
                "legal_policy_reference": "policyref://gs12-adapter-test",
                "currency": "AED",
                "max_total_budget_minor": 10000,
                "max_daily_budget_minor": 2000,
                "max_cpa_minor": 2500,
                "min_roas": 1.25,
            },
        )
    return owner, pilot, cap


def test_request_builders_are_paused_and_match_supported_meta_shapes() -> None:
    campaign = adapter.build_campaign_create(ACCOUNT_ID, name="Campaign")
    assert campaign.path == f"/act_{ACCOUNT_ID}/campaigns"
    assert campaign.form == {
        "name": "Campaign",
        "objective": "OUTCOME_TRAFFIC",
        "status": "PAUSED",
        "special_ad_categories": [],
        "is_adset_budget_sharing_enabled": False,
    }

    adset = adapter.build_adset_create(
        ACCOUNT_ID,
        campaign_id="223456789012345",
        name="Ad Set",
        daily_budget_minor=100,
        targeting={"geo_locations": {"countries": ["AE"]}},
    )
    assert adset.path == f"/act_{ACCOUNT_ID}/adsets"
    assert adset.form["status"] == "PAUSED"
    assert adset.form["daily_budget"] == 100
    assert adset.form["billing_event"] == "IMPRESSIONS"
    assert adset.form["optimization_goal"] == "LINK_CLICKS"

    creative = adapter.build_creative_create(
        ACCOUNT_ID,
        name="Creative",
        object_story_spec={
            "page_id": "323456789012345",
            "link_data": {"link": "https://example.invalid"},
        },
    )
    assert creative.path == f"/act_{ACCOUNT_ID}/adcreatives"
    assert set(creative.form) == {"name", "object_story_spec"}

    ad = adapter.build_ad_create(
        ACCOUNT_ID,
        name="Ad",
        adset_id="423456789012345",
        creative_id="523456789012345",
    )
    assert ad.path == f"/act_{ACCOUNT_ID}/ads"
    assert ad.form["status"] == "PAUSED"
    assert ad.form["creative"] == {"creative_id": "523456789012345"}

    assert adapter.build_status_update("623456789012345", "PAUSED").form == {
        "status": "PAUSED"
    }
    assert adapter.build_status_update("623456789012345", "ACTIVE").form == {
        "status": "ACTIVE"
    }
    assert len(adapter.adapter_contract_digest()) == 64


def test_request_builders_reject_secret_material_and_unbounded_values() -> None:
    with pytest.raises(
        adapter.MetaLiveExecutionAdapterError, match="credential-material-forbidden"
    ):
        adapter.build_campaign_create(ACCOUNT_ID, name="secret=must-not-pass")
    with pytest.raises(
        adapter.MetaLiveExecutionAdapterError, match="credential-material-forbidden"
    ):
        adapter.build_adset_create(
            ACCOUNT_ID,
            campaign_id="223456789012345",
            name="Ad Set",
            daily_budget_minor=100,
            targeting={"access_token": "fake"},
        )
    with pytest.raises(
        adapter.MetaLiveExecutionAdapterError, match="daily-budget-invalid"
    ):
        adapter.build_adset_create(
            ACCOUNT_ID,
            campaign_id="223456789012345",
            name="Ad Set",
            daily_budget_minor=0,
            targeting={},
        )
    with pytest.raises(
        adapter.MetaLiveExecutionAdapterError, match="status-not-allowlisted"
    ):
        adapter.build_status_update("623456789012345", "DELETED")


@pytest.mark.asyncio
async def test_dry_run_verification_binds_adapter_without_enabling_spend() -> None:
    async with SessionLocal() as session:
        owner, pilot, capability = await _fixture(session)
        result = await adapter.verify_adapter_dry_run(session, owner, pilot.id)
        await session.flush()
        evidence = dict(capability.evidence or {})
        assert result["execution_adapter_verified"] is True
        assert result["provider_call_executed"] is False
        assert result["spend_executed"] is False
        assert result["real_spend_allowed"] is False
        assert evidence["execution_adapter_verified"] is True
        assert evidence["execution_adapter_scope_ref"] == pilot.scope_ref
        assert evidence["execution_adapter_organization_id"] == pilot.organization_id
        assert evidence["spend_allowed"] is False
        assert pilot.live_provider_mutation_allowed is False
        assert pilot.real_spend_allowed is False

        check = await pilots.readiness(
            session,
            owner,
            pilot.id,
            require_launch_authorization=False,
        )
        assert check["provider_gate"] is True
        assert check["execution_adapter_gate"] is True
        assert "provider-write-capability-unverified" not in check["blocked_reasons"]
        assert (
            "provider-live-execution-adapter-unverified" not in check["blocked_reasons"]
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_guarded_executor_denies_before_token_read_when_pilot_is_not_armed(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, pilot, _ = await _fixture(session)
        await adapter.verify_adapter_dry_run(session, owner, pilot.id)

        def must_not_read(_path: str) -> str:
            raise AssertionError("token must not be read before runtime authorization")

        monkeypatch.setattr(adapter.meta_owned, "_read_token", must_not_read)
        spec = adapter.build_campaign_create(ACCOUNT_ID, name="Blocked")
        with pytest.raises(
            adapter.MetaLiveExecutionAdapterError,
            match="runtime-authorization-denied:pilot-not-armed",
        ):
            await adapter.execute_guarded_request(
                session,
                pilot_id=pilot.id,
                scope_ref=SCOPE_REF,
                account_id=ACCOUNT_ID,
                request_spec=spec,
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_guarded_executor_uses_runtime_caps_with_fake_transport(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, pilot, _ = await _fixture(session, ready_controls=True)
        await adapter.verify_adapter_dry_run(session, owner, pilot.id)
        await pilots.authorize_launch(session, owner, pilot.id)
        armed = await pilots.arm_pilot(session, owner, pilot.id)
        assert armed.real_spend_allowed is True

        monkeypatch.setattr(
            adapter.meta_owned,
            "_safe_config",
            lambda: ("/run/operator-secrets/test", "v26.0"),
        )
        monkeypatch.setattr(
            adapter.meta_owned, "_read_token", lambda _path: "fake-token"
        )
        calls: list[tuple[str, str, dict[str, list[str]]]] = []

        def opener(request, timeout=20):
            from urllib.parse import parse_qs

            parsed = parse_qs((request.data or b"").decode())
            calls.append((request.get_method(), request.full_url, parsed))
            if request.get_method() == "GET":
                return io.BytesIO(
                    json.dumps(
                        {
                            "id": "223456789012345",
                            "account_id": ACCOUNT_ID,
                        }
                    ).encode()
                )
            return io.BytesIO(json.dumps({"id": "723456789012345"}).encode())

        spec = adapter.build_adset_create(
            ACCOUNT_ID,
            campaign_id="223456789012345",
            name="Guarded Ad Set",
            daily_budget_minor=1500,
            targeting={"geo_locations": {"countries": ["AE"]}},
        )
        payload = await adapter.execute_guarded_request(
            session,
            pilot_id=pilot.id,
            scope_ref=SCOPE_REF,
            account_id=ACCOUNT_ID,
            request_spec=spec,
            opener=opener,
        )
        assert payload["id"] == "723456789012345"
        assert len(calls) == 2
        assert calls[0][0] == "GET"
        assert calls[0][1].endswith("/v26.0/223456789012345?fields=id,account_id")
        assert calls[1][0] == "POST"
        assert calls[1][1].endswith(f"/v26.0/act_{ACCOUNT_ID}/adsets")
        assert calls[1][2]["daily_budget"] == ["1500"]
        assert calls[1][2]["status"] == ["PAUSED"]
        await session.rollback()


@pytest.mark.asyncio
async def test_guarded_executor_rejects_cross_account_parent_before_mutation(
    monkeypatch,
) -> None:
    async with SessionLocal() as session:
        owner, pilot, _ = await _fixture(session, ready_controls=True)
        await adapter.verify_adapter_dry_run(session, owner, pilot.id)
        await pilots.authorize_launch(session, owner, pilot.id)
        await pilots.arm_pilot(session, owner, pilot.id)

        monkeypatch.setattr(
            adapter.meta_owned,
            "_safe_config",
            lambda: ("/run/operator-secrets/test", "v26.0"),
        )
        monkeypatch.setattr(
            adapter.meta_owned, "_read_token", lambda _path: "fake-token"
        )
        calls: list[tuple[str, str]] = []

        def opener(request, timeout=20):
            calls.append((request.get_method(), request.full_url))
            if request.get_method() != "GET":
                raise AssertionError("mutation must not execute after account mismatch")
            return io.BytesIO(
                json.dumps(
                    {
                        "id": "223456789012345",
                        "account_id": "999999999999999",
                    }
                ).encode()
            )

        spec = adapter.build_adset_create(
            ACCOUNT_ID,
            campaign_id="223456789012345",
            name="Cross-account Ad Set",
            daily_budget_minor=1000,
            targeting={"geo_locations": {"countries": ["AE"]}},
        )
        with pytest.raises(
            adapter.MetaLiveExecutionAdapterError,
            match="provider-object-account-mismatch",
        ):
            await adapter.execute_guarded_request(
                session,
                pilot_id=pilot.id,
                scope_ref=SCOPE_REF,
                account_id=ACCOUNT_ID,
                request_spec=spec,
                opener=opener,
            )
        assert calls == [
            (
                "GET",
                "https://graph.facebook.com/v26.0/223456789012345?fields=id,account_id",
            )
        ]
        await session.rollback()
