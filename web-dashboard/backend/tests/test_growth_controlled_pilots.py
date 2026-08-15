from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    GrowthSocialProviderCapability,
    Organization,
    User,
)
from app.services import growth_controlled_pilots as pilots


def _actor(
    org_id: str, user_id: str, email: str, role: str = "Super Owner"
) -> UserRecord:
    return UserRecord(
        id=user_id,
        email=email,
        name="GS12 Owner",
        role=role,
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS12",
        organization_plan="test",
        permissions=["*"],
        status="active",
        auth_version=1,
    )


async def _capability(
    session,
    provider: str,
    capability: str,
    *,
    state: str,
    mutation_class: str,
    evidence: dict | None = None,
):
    row = await session.scalar(
        select(GrowthSocialProviderCapability).where(
            GrowthSocialProviderCapability.provider == provider,
            GrowthSocialProviderCapability.capability == capability,
        )
    )
    if row is None:
        row = GrowthSocialProviderCapability(
            provider=provider,
            capability=capability,
            verification_state=state,
            mutation_class=mutation_class,
            evidence=dict(evidence or {}),
            version=1,
        )
        session.add(row)
    else:
        row.verification_state = state
        row.mutation_class = mutation_class
        row.evidence = dict(evidence or {})
        row.version += 1
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_read_only_live_pilot_is_verified_without_mutation_or_spend(
    monkeypatch,
) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs12-org-{suffix}"
    owner_id = f"gs12-owner-{suffix}"
    owner = _actor(org_id, owner_id, f"gs12-{suffix}@example.invalid")

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS12 Read Only",
                slug=f"gs12-ro-{suffix}",
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
        await _capability(
            session,
            "meta",
            "ads_read",
            state="read_only_verified",
            mutation_class="read",
            evidence={"mutation_allowed": False, "spend_allowed": False},
        )

        with pytest.raises(
            pilots.GrowthControlledPilotError, match="unsupported-provider-scope"
        ):
            await pilots.create_pilot(
                session,
                owner,
                {
                    "provider": "meta",
                    "provider_scope": "arbitrary_scope",
                    "mode": "read_only",
                    "owner_approval_reference": "gs12-test-owner-approval",
                },
            )

        pilot = await pilots.create_pilot(
            session,
            owner,
            {
                "provider": "meta",
                "provider_scope": "owned_assets",
                "mode": "read_only",
                "owner_approval_reference": "gs12-test-owner-approval",
            },
        )
        check = await pilots.readiness(session, owner, pilot.id)
        assert check["ready_to_arm"] is True
        assert check["provider_gate"] is True
        assert check["legal_gate"] is True
        assert check["budget_gate"] is True
        assert check["stop_loss_gate"] is True
        assert check["live_provider_mutation_allowed"] is False
        assert check["real_spend_allowed"] is False

        monkeypatch.setattr(
            pilots.growth_meta_owned_connector,
            "probe_meta_owned_assets_read_only",
            lambda: {
                "ad_accounts_count": 2,
                "active_ad_accounts_count": 1,
                "result_page_truncated": False,
                "provider_call_allowed": True,
                "mutation_allowed": False,
                "spend_allowed": False,
                "credential_ref": "must-not-persist",
            },
        )
        validated = await pilots.validate_read_only_live(session, owner, pilot.id)
        evidence = dict(validated.evidence["read_only_live_validation"])
        assert validated.status == "read_only_validated"
        assert evidence["ad_accounts_count"] == 2
        assert evidence["active_ad_accounts_count"] == 1
        assert evidence["mutation_allowed"] is False
        assert evidence["spend_allowed"] is False
        assert evidence["raw_secret_persisted"] is False
        assert "credential_ref" not in evidence

        armed = await pilots.arm_pilot(session, owner, pilot.id)
        assert armed.status == "read_only_armed"
        assert armed.live_provider_mutation_allowed is False
        assert armed.real_spend_allowed is False

        disarmed = await pilots.disarm_pilot(
            session, owner, pilot.id, reason="test-emergency-disarm"
        )
        assert disarmed.status == "disarmed"
        assert disarmed.launch_authorized is False
        assert disarmed.live_provider_mutation_allowed is False
        assert disarmed.real_spend_allowed is False
        await session.rollback()


@pytest.mark.asyncio
async def test_live_spend_pilot_fails_closed_until_every_gate_is_verified() -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs12-live-org-{suffix}"
    owner_id = f"gs12-live-owner-{suffix}"
    owner = _actor(org_id, owner_id, f"gs12-live-{suffix}@example.invalid")

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS12 Live Spend",
                slug=f"gs12-live-{suffix}",
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
        capability = await _capability(
            session,
            "meta",
            "ads.manage",
            state="unverified",
            mutation_class="write",
            evidence={
                "mutation_allowed": False,
                "spend_allowed": False,
                "execution_adapter_verified": False,
            },
        )

        with pytest.raises(
            pilots.GrowthControlledPilotError,
            match="live-spend-scope-reference-required",
        ):
            await pilots.create_pilot(
                session,
                owner,
                {
                    "organization_id": org_id,
                    "provider": "meta",
                    "provider_scope": "managed_ad_account",
                    "mode": "live_spend",
                    "owner_approval_reference": "gs12-test-phase-approval",
                },
            )

        pilot = await pilots.create_pilot(
            session,
            owner,
            {
                "organization_id": org_id,
                "provider": "meta",
                "provider_scope": "managed_ad_account",
                "scope_ref": "accountref://synthetic",
                "mode": "live_spend",
                "owner_approval_reference": "gs12-test-phase-approval",
            },
        )
        initial = await pilots.readiness(session, owner, pilot.id)
        assert initial["ready_to_arm"] is False
        assert set(initial["blocked_reasons"]) >= {
            "provider-write-capability-unverified",
            "provider-live-execution-adapter-unverified",
            "legal-policy-acknowledgement-missing",
            "budget-controls-missing",
            "stop-loss-controls-missing",
            "launch-authorization-missing",
        }
        assert pilot.real_spend_allowed is False
        assert pilot.live_provider_mutation_allowed is False

        configured = await pilots.configure_controls(
            session,
            owner,
            pilot.id,
            {
                "legal_policy_acknowledged": True,
                "legal_policy_reference": "policyref://gs12-reviewed",
                "currency": "AED",
                "max_total_budget_minor": 10000,
                "max_daily_budget_minor": 2500,
                "max_cpa_minor": 3000,
                "min_roas": 1.25,
            },
        )
        assert configured.launch_authorized is False
        assert configured.real_spend_allowed is False
        assert configured.live_provider_mutation_allowed is False

        with pytest.raises(
            pilots.GrowthControlledPilotError,
            match="provider-write-capability-unverified",
        ):
            await pilots.authorize_launch(session, owner, pilot.id)

        capability.verification_state = "live_write_verified"
        capability.mutation_class = "write"
        capability.evidence = {
            "mutation_allowed": True,
            "spend_allowed": True,
            "execution_adapter_verified": False,
        }
        await session.flush()
        prelaunch = await pilots.readiness(
            session,
            owner,
            pilot.id,
            require_launch_authorization=False,
        )
        assert prelaunch["provider_gate"] is True
        assert prelaunch["execution_adapter_gate"] is False
        assert (
            "provider-live-execution-adapter-unverified" in prelaunch["blocked_reasons"]
        )

        capability.evidence = {
            "mutation_allowed": True,
            "spend_allowed": True,
            "execution_adapter_verified": True,
        }
        await session.flush()
        authorized = await pilots.authorize_launch(session, owner, pilot.id)
        assert authorized.launch_authorized is True
        assert authorized.real_spend_allowed is False
        assert authorized.live_provider_mutation_allowed is False

        ready = await pilots.readiness(session, owner, pilot.id)
        assert ready["ready_to_arm"] is True
        assert ready["blocked_reasons"] == []

        armed = await pilots.arm_pilot(session, owner, pilot.id)
        assert armed.status == "armed"
        assert armed.real_spend_allowed is True
        assert armed.live_provider_mutation_allowed is True

        reset = await pilots.configure_controls(
            session,
            owner,
            pilot.id,
            {"max_daily_budget_minor": 2000},
        )
        assert reset.launch_authorized is False
        assert reset.real_spend_allowed is False
        assert reset.live_provider_mutation_allowed is False

        disarmed = await pilots.disarm_pilot(
            session, owner, pilot.id, reason="operator-stop"
        )
        assert disarmed.status == "disarmed"
        assert disarmed.real_spend_allowed is False
        assert disarmed.live_provider_mutation_allowed is False
        await session.rollback()


@pytest.mark.asyncio
async def test_non_super_owner_cannot_create_or_manage_pilot() -> None:
    actor = _actor("o", "u", "owner@example.invalid", role="Owner")
    async with SessionLocal() as session:
        with pytest.raises(
            pilots.GrowthControlledPilotError, match="super-owner-required"
        ):
            await pilots.create_pilot(
                session,
                actor,
                {
                    "provider": "meta",
                    "provider_scope": "owned_assets",
                    "mode": "read_only",
                    "owner_approval_reference": "not-authorized",
                },
            )


def test_control_validation_rejects_secret_material_and_unsafe_expiry() -> None:
    with pytest.raises(
        pilots.GrowthControlledPilotError, match="raw-credential-material-forbidden"
    ):
        pilots._safe_reference("token=forbidden", max_length=240, required=True)
    with pytest.raises(
        pilots.GrowthControlledPilotError, match="pilot-expiry-exceeds-7-days"
    ):
        pilots._normalize_expiry(pilots._now() + pilots.timedelta(days=8))
    with pytest.raises(
        pilots.GrowthControlledPilotError, match="max-total-budget-too-large"
    ):
        pilots._positive_or_none(pilots.MAX_MONEY_MINOR + 1, "max-total-budget")
    with pytest.raises(
        pilots.GrowthControlledPilotError, match="min-roas-must-be-positive-and-finite"
    ):
        pilots._positive_float_or_none(float("inf"), "min-roas")


async def _ready_live_pilot(session, owner: UserRecord, org_id: str, scope_ref: str):
    capability = await _capability(
        session,
        "meta",
        "ads.manage",
        state="live_write_verified",
        mutation_class="write",
        evidence={
            "mutation_allowed": True,
            "spend_allowed": True,
            "execution_adapter_verified": True,
        },
    )
    pilot = await pilots.create_pilot(
        session,
        owner,
        {
            "organization_id": org_id,
            "provider": "meta",
            "provider_scope": "managed_ad_account",
            "scope_ref": scope_ref,
            "mode": "live_spend",
            "owner_approval_reference": "gs12-runtime-hardening-approval",
        },
    )
    await pilots.configure_controls(
        session,
        owner,
        pilot.id,
        {
            "legal_policy_acknowledged": True,
            "legal_policy_reference": "policyref://gs12-runtime-hardening",
            "currency": "AED",
            "max_total_budget_minor": 10000,
            "max_daily_budget_minor": 2000,
            "max_cpa_minor": 2500,
            "min_roas": 1.25,
        },
    )
    await pilots.authorize_launch(session, owner, pilot.id)
    return pilot, capability


@pytest.mark.asyncio
async def test_runtime_authorization_auto_disarms_expired_armed_pilot() -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs12-runtime-org-{suffix}"
    owner_id = f"gs12-runtime-owner-{suffix}"
    owner = _actor(org_id, owner_id, f"runtime-{suffix}@example.invalid")
    scope_ref = f"accountref://runtime-{suffix}"

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS12 Runtime Guard",
                slug=f"gs12-runtime-{suffix}",
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
        pilot, _ = await _ready_live_pilot(session, owner, org_id, scope_ref)
        armed = await pilots.arm_pilot(session, owner, pilot.id)
        assert armed.real_spend_allowed is True
        armed.expires_at = pilots._now() - pilots.timedelta(seconds=1)
        await session.flush()

        authorization = await pilots.runtime_authorization(
            session,
            pilot.id,
            provider="meta",
            scope_ref=scope_ref,
        )
        assert authorization["authorized"] is False
        assert authorization["auto_disarmed"] is True
        assert "pilot-expired" in authorization["blocked_reasons"]
        assert pilot.status == "auto_disarmed"
        assert pilot.launch_authorized is False
        assert pilot.live_provider_mutation_allowed is False
        assert pilot.real_spend_allowed is False
        await session.rollback()


@pytest.mark.asyncio
async def test_runtime_reconciliation_auto_disarms_when_provider_gate_is_revoked() -> (
    None
):
    suffix = uuid4().hex[:10]
    org_id = f"gs12-reconcile-org-{suffix}"
    owner_id = f"gs12-reconcile-owner-{suffix}"
    owner = _actor(org_id, owner_id, f"reconcile-{suffix}@example.invalid")
    scope_ref = f"accountref://reconcile-{suffix}"

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS12 Reconcile Guard",
                slug=f"gs12-reconcile-{suffix}",
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
        pilot, capability = await _ready_live_pilot(session, owner, org_id, scope_ref)
        await pilots.arm_pilot(session, owner, pilot.id)
        capability.verification_state = "sandbox_write_verified"
        capability.evidence = {
            "mutation_allowed": False,
            "spend_allowed": False,
            "execution_adapter_verified": False,
        }
        await session.flush()

        result = await pilots.reconcile_runtime_pilots(session)
        assert result == {"checked": 1, "auto_disarmed": 1}
        assert pilot.status == "auto_disarmed"
        assert pilot.launch_authorized is False
        assert pilot.live_provider_mutation_allowed is False
        assert pilot.real_spend_allowed is False
        assert any(
            item.startswith("runtime-guard:provider-write-capability-unverified")
            for item in pilot.blocked_reasons
        )
        await session.rollback()


@pytest.mark.asyncio
async def test_only_one_live_spend_pilot_can_arm_for_same_provider_scope() -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs12-single-scope-org-{suffix}"
    owner_id = f"gs12-single-scope-owner-{suffix}"
    owner = _actor(org_id, owner_id, f"single-{suffix}@example.invalid")
    scope_ref = f"accountref://single-{suffix}"

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS12 Single Scope",
                slug=f"gs12-single-{suffix}",
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
        first, _ = await _ready_live_pilot(session, owner, org_id, scope_ref)
        second, _ = await _ready_live_pilot(session, owner, org_id, scope_ref)
        await pilots.arm_pilot(session, owner, first.id)

        with pytest.raises(
            pilots.GrowthControlledPilotError, match="pilot-scope-already-armed"
        ):
            await pilots.arm_pilot(session, owner, second.id)
        assert first.real_spend_allowed is True
        assert second.real_spend_allowed is False
        assert second.live_provider_mutation_allowed is False
        await session.rollback()


@pytest.mark.asyncio
async def test_database_rejects_two_live_flags_for_same_provider_scope() -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs12-db-scope-org-{suffix}"
    owner_id = f"gs12-db-scope-owner-{suffix}"
    owner = _actor(org_id, owner_id, f"db-scope-{suffix}@example.invalid")
    scope_ref = f"accountref://db-scope-{suffix}"

    async with SessionLocal() as session:
        session.add(
            Organization(
                id=org_id,
                name="GS12 DB Scope Invariant",
                slug=f"gs12-db-scope-{suffix}",
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
        first, _ = await _ready_live_pilot(session, owner, org_id, scope_ref)
        second, _ = await _ready_live_pilot(session, owner, org_id, scope_ref)

        first.real_spend_allowed = True
        await session.flush()
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                second.real_spend_allowed = True
                await session.flush()
        await session.rollback()
