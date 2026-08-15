from __future__ import annotations

import io
import json
from copy import deepcopy
from urllib.parse import parse_qs
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.auth import UserRecord
from app.db.base import SessionLocal
from app.db.models import (
    AuditEvent,
    GrowthSocialProviderCapability,
    Organization,
    User,
)
from app.services import growth_controlled_pilots as pilots
from app.services import growth_meta_owned_write as owned_write

ACCOUNT_ID = "123456789012345"
CAMPAIGN_ID = "9988776655443322"
SECRET = "unit-test-owned-secret-material"


def _response(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _configure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        owned_write.meta_owned.META_TOKEN_FILE_ENV,
        "/run/operator-secrets/meta-owned-test",
    )
    monkeypatch.setenv(owned_write.META_TARGET_ACCOUNT_ID_ENV, ACCOUNT_ID)
    monkeypatch.setenv(
        owned_write.meta_owned.META_GRAPH_API_VERSION_ENV,
        "v26.0",
    )
    monkeypatch.setenv(owned_write.META_CONFIRM_ENV, owned_write.META_CONFIRM_VALUE)
    monkeypatch.setattr(owned_write.meta_owned, "_read_token", lambda _: SECRET)


def _success_opener(calls: list[tuple[str, str]]):
    def opener(request, timeout=20):
        assert timeout == 20
        method = request.get_method()
        url = request.full_url
        calls.append((method, url))
        assert SECRET not in url
        assert request.headers.get("Authorization", "").startswith("Bearer ")

        if method == "GET" and "/me/adaccounts?" in url:
            return _response(
                {
                    "data": [{"id": f"act_{ACCOUNT_ID}", "account_status": 1}],
                    "paging": {},
                }
            )
        if method == "GET" and url.startswith(
            f"https://graph.facebook.com/v26.0/act_{ACCOUNT_ID}?fields="
        ):
            return _response(
                {
                    "id": f"act_{ACCOUNT_ID}",
                    "name": "AIONEX Production Ads",
                    "currency": "AED",
                    "timezone_name": "Asia/Dubai",
                    "account_status": 1,
                }
            )
        if method == "GET" and url.endswith("/me/permissions"):
            return _response(
                {
                    "data": [
                        {"permission": "ads_management", "status": "granted"},
                        {"permission": "ads_read", "status": "granted"},
                    ]
                }
            )
        if method == "POST" and url.endswith(f"/act_{ACCOUNT_ID}/campaigns"):
            form = parse_qs((request.data or b"").decode("utf-8"))
            assert set(form) == {
                "name",
                "objective",
                "status",
                "special_ad_categories",
                "is_adset_budget_sharing_enabled",
            }
            assert form["objective"] == ["OUTCOME_TRAFFIC"]
            assert form["status"] == ["PAUSED"]
            assert form["special_ad_categories"] == ["[]"]
            assert form["is_adset_budget_sharing_enabled"] == ["false"]
            for forbidden in (
                "daily_budget",
                "lifetime_budget",
                "budget",
                "spend_cap",
                "bid_amount",
                "adset_id",
                "ad_set_id",
                "creative_id",
                "audience",
            ):
                assert forbidden not in form
            return _response({"id": CAMPAIGN_ID})
        if method == "GET" and url.startswith(
            f"https://graph.facebook.com/v26.0/{CAMPAIGN_ID}?fields="
        ):
            return _response(
                {
                    "id": CAMPAIGN_ID,
                    "name": "AIONEX GS12 Owned No-Spend Write Validation",
                    "status": "PAUSED",
                    "objective": "OUTCOME_TRAFFIC",
                }
            )
        if method == "DELETE" and url.endswith(f"/{CAMPAIGN_ID}"):
            return _response({"success": True})
        raise AssertionError(f"unexpected request: {method} {url}")

    return opener


def test_scope_reference_is_deterministic_and_does_not_expose_account_id(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure(monkeypatch)
    first = owned_write.opaque_scope_ref(ACCOUNT_ID)
    second = owned_write.opaque_scope_ref(ACCOUNT_ID)
    assert first == second
    assert first.startswith("accountref://meta/sha256/")
    assert ACCOUNT_ID not in first

    owned_write._print_safe_scope_ref()
    output = capsys.readouterr().out
    assert first in output
    assert ACCOUNT_ID not in output
    assert "provider_call_executed=false" in output


def test_confirmation_and_target_account_id_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(owned_write.META_CONFIRM_ENV, raising=False)
    with pytest.raises(
        owned_write.MetaOwnedWriteValidationError,
        match="confirmation-required",
    ):
        owned_write._require_confirmation()

    monkeypatch.setenv(owned_write.META_TARGET_ACCOUNT_ID_ENV, "not-an-account")
    with pytest.raises(
        owned_write.MetaOwnedWriteValidationError,
        match="account-id-invalid",
    ):
        owned_write._target_account_id()


def test_owned_no_spend_write_cycle_is_paused_budgetless_and_deleted() -> None:
    calls: list[tuple[str, str]] = []
    result = owned_write._provider_write_cycle(
        account_id=ACCOUNT_ID,
        api_version="v26.0",
        token=SECRET,
        opener=_success_opener(calls),
    )
    assert result["campaign_created"] is True
    assert result["campaign_status_verified"] == "PAUSED"
    assert result["campaign_deleted"] is True
    assert result["ad_set_created"] is False
    assert result["ad_created"] is False
    assert result["budget_configured"] is False
    assert result["real_spend_minor"] == 0
    assert [method for method, _ in calls] == [
        "GET",
        "GET",
        "GET",
        "POST",
        "GET",
        "DELETE",
    ]


def test_owned_write_rejects_sandbox_named_target_before_mutation() -> None:
    calls: list[tuple[str, str]] = []

    def opener(request, timeout=20):
        method = request.get_method()
        url = request.full_url
        calls.append((method, url))
        if method == "GET" and "/me/adaccounts?" in url:
            return _response(
                {
                    "data": [{"id": f"act_{ACCOUNT_ID}", "account_status": 1}],
                    "paging": {},
                }
            )
        if method == "GET" and f"/act_{ACCOUNT_ID}?fields=" in url:
            return _response(
                {
                    "id": f"act_{ACCOUNT_ID}",
                    "name": "Unexpected Sandbox Account",
                    "currency": "AED",
                    "timezone_name": "Asia/Dubai",
                    "account_status": 1,
                }
            )
        raise AssertionError(f"unexpected request: {method} {url}")

    with pytest.raises(
        owned_write.MetaOwnedWriteValidationError,
        match="target-not-live-owned",
    ):
        owned_write._provider_write_cycle(
            account_id=ACCOUNT_ID,
            api_version="v26.0",
            token=SECRET,
            opener=opener,
        )
    assert all(method == "GET" for method, _ in calls)


def test_owned_write_cleanup_failure_takes_precedence() -> None:
    calls: list[tuple[str, str]] = []
    success = _success_opener(calls)

    def opener(request, timeout=20):
        if request.get_method() == "DELETE":
            calls.append(("DELETE", request.full_url))
            return _response({"success": False})
        return success(request, timeout=timeout)

    with pytest.raises(
        owned_write.MetaOwnedWriteValidationError,
        match="campaign-cleanup-failed",
    ):
        owned_write._provider_write_cycle(
            account_id=ACCOUNT_ID,
            api_version="v26.0",
            token=SECRET,
            opener=opener,
        )
    assert any(method == "DELETE" for method, _ in calls)


@pytest.mark.asyncio
async def test_live_write_scope_binding_and_owned_validator_record_safe_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    suffix = uuid4().hex[:10]
    org_id = str(uuid4())
    owner_id = str(uuid4())
    scope_ref = owned_write.opaque_scope_ref(ACCOUNT_ID)
    actor = UserRecord(
        id=owner_id,
        email=f"gs12-owned-write-{suffix}@example.invalid",
        name="GS12 Owned Write Owner",
        role="Super Owner",
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS12 Owned Write",
        organization_plan="test",
        permissions=["*"],
        status="active",
        auth_version=1,
    )

    pilot_id: str | None = None
    capability_before: dict | None = None
    capability_existed = False
    try:
        async with SessionLocal() as session:
            existing = await session.scalar(
                select(GrowthSocialProviderCapability).where(
                    GrowthSocialProviderCapability.provider == "meta",
                    GrowthSocialProviderCapability.capability == "ads.manage",
                )
            )
            if existing is not None:
                capability_existed = True
                capability_before = {
                    "verification_state": existing.verification_state,
                    "mutation_class": existing.mutation_class,
                    "evidence": deepcopy(existing.evidence or {}),
                    "verified_at": existing.verified_at,
                    "version": existing.version,
                }

            session.add(
                Organization(
                    id=org_id,
                    name="GS12 Owned Write",
                    slug=f"gs12-owned-write-{suffix}",
                    plan="test",
                    status="active",
                )
            )
            await session.flush()
            session.add(
                User(
                    id=owner_id,
                    organization_id=org_id,
                    email=actor.email,
                    name=actor.name,
                    password_hash="unused",
                    status="active",
                    auth_version=1,
                )
            )
            await session.flush()
            pilot = await pilots.create_pilot(
                session,
                actor,
                {
                    "organization_id": org_id,
                    "provider": "meta",
                    "provider_scope": "managed_ad_account",
                    "scope_ref": scope_ref,
                    "mode": "live_spend",
                    "owner_approval_reference": "gs12-owned-write-test",
                },
            )
            assert pilot.legal_policy_acknowledged is False
            with pytest.raises(
                owned_write.MetaOwnedWriteValidationError,
                match="meta-owned-write-no-spend-approval-missing",
            ):
                await owned_write._lock_and_validate_pilot(
                    session,
                    pilot.id,
                    expected_scope_ref=scope_ref,
                )
            await pilots.authorize_no_spend_write_validation(
                session,
                actor,
                pilot.id,
                reference="approvalref://gs12-owned-write-single-test",
            )
            assert pilot.legal_policy_acknowledged is False
            pilot_id = pilot.id
            await session.commit()

        calls: list[tuple[str, str]] = []
        evidence = await owned_write.validate_and_record(
            pilot_id,
            opener=_success_opener(calls),
        )
        assert evidence["scope_ref"] == scope_ref
        assert evidence["organization_id"] == org_id
        assert evidence["mutation_allowed"] is True
        assert evidence["spend_allowed"] is False
        assert evidence["execution_adapter_verified"] is False
        assert evidence["real_spend_minor"] == 0
        assert ACCOUNT_ID not in repr(evidence)
        assert SECRET not in repr(evidence)

        async with SessionLocal() as session:
            capability = await session.scalar(
                select(GrowthSocialProviderCapability).where(
                    GrowthSocialProviderCapability.provider == "meta",
                    GrowthSocialProviderCapability.capability == "ads.manage",
                )
            )
            assert capability is not None
            stored = dict(capability.evidence or {})
            assert capability.verification_state == "live_write_verified"
            assert capability.mutation_class == "write"
            assert stored["live_scope_ref"] == scope_ref
            assert stored["live_organization_id"] == org_id
            assert stored["mutation_allowed"] is True
            assert stored["spend_allowed"] is False
            assert stored["execution_adapter_verified"] is False
            assert stored["raw_secret_persisted"] is False

            pilot = await session.get(pilots.GrowthControlledPilot, pilot_id)
            assert pilot is not None
            assert pilot.live_provider_mutation_allowed is False
            assert pilot.real_spend_allowed is False
            approval = dict(pilot.evidence[pilots.NO_SPEND_WRITE_APPROVAL_EVIDENCE_KEY])
            assert approval["approved"] is True
            assert approval["scope"] == pilots.NO_SPEND_WRITE_APPROVAL_SCOPE
            assert approval["consumed"] is True
            assert approval["completed"] is True
            assert approval["provider_call_executed"] is True
            assert approval["spend_executed"] is False
            assert approval["real_spend_minor"] == 0
            assert pilot.legal_policy_acknowledged is False
            assert (
                pilot.evidence["live_no_spend_write_validation"]["campaign_deleted"]
                is True
            )

            with pytest.raises(
                owned_write.MetaOwnedWriteValidationError,
                match="meta-owned-write-no-spend-approval-consumed",
            ):
                await owned_write._lock_and_validate_pilot(
                    session,
                    pilot_id,
                    expected_scope_ref=scope_ref,
                )

            readiness = await pilots.readiness(
                session,
                actor,
                pilot_id,
                require_launch_authorization=False,
            )
            assert readiness["provider_gate"] is True
            assert readiness["execution_adapter_gate"] is False
            assert (
                "provider-write-capability-unverified"
                not in readiness["blocked_reasons"]
            )
            assert (
                "provider-live-execution-adapter-unverified"
                in readiness["blocked_reasons"]
            )

            started_audit = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action
                    == "growth.pilot.no_spend_write_validation_started",
                    AuditEvent.resource_id == pilot_id,
                )
            )
            assert started_audit is not None
            assert started_audit.details["approval_consumed"] is True
            assert started_audit.details["spend_executed"] is False

            audit = await session.scalar(
                select(AuditEvent).where(
                    AuditEvent.action == "growth.pilot.live_write_verified_no_spend",
                    AuditEvent.resource_id == pilot_id,
                )
            )
            assert audit is not None
            assert audit.details["real_spend_minor"] == 0
            assert audit.details["spend_allowed"] is False
    finally:
        if pilot_id is not None:
            async with SessionLocal() as session:
                await session.execute(
                    delete(AuditEvent).where(AuditEvent.resource_id == pilot_id)
                )
                organization = await session.get(Organization, org_id)
                if organization is not None:
                    await session.delete(organization)
                capability = await session.scalar(
                    select(GrowthSocialProviderCapability).where(
                        GrowthSocialProviderCapability.provider == "meta",
                        GrowthSocialProviderCapability.capability == "ads.manage",
                    )
                )
                if capability is not None:
                    if capability_existed and capability_before is not None:
                        capability.verification_state = capability_before[
                            "verification_state"
                        ]
                        capability.mutation_class = capability_before["mutation_class"]
                        capability.evidence = capability_before["evidence"]
                        capability.verified_at = capability_before["verified_at"]
                        capability.version = capability_before["version"]
                    else:
                        await session.delete(capability)
                await session.commit()


@pytest.mark.asyncio
async def test_no_spend_write_approval_is_single_use_even_when_token_read_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid4().hex[:10]
    org_id = f"gs12-owned-write-fail-{suffix}"
    owner_id = f"gs12-owned-write-owner-{suffix}"
    scope_ref = owned_write.opaque_scope_ref(ACCOUNT_ID)
    actor = UserRecord(
        id=owner_id,
        email=f"owner-{suffix}@example.invalid",
        name="GS12 Owned Write Owner",
        role="Super Owner",
        password_hash="unused",
        organization_id=org_id,
        organization_name="GS12 Owned Write Failure",
        organization_plan="test",
        permissions=["*"],
        status="active",
        auth_version=1,
    )
    pilot_id: str | None = None

    monkeypatch.setenv(
        owned_write.meta_owned.META_TOKEN_FILE_ENV,
        "/run/operator-secrets/meta-owned-test",
    )
    monkeypatch.setenv(owned_write.META_TARGET_ACCOUNT_ID_ENV, ACCOUNT_ID)
    monkeypatch.setenv(
        owned_write.meta_owned.META_GRAPH_API_VERSION_ENV,
        "v26.0",
    )
    monkeypatch.setenv(owned_write.META_CONFIRM_ENV, owned_write.META_CONFIRM_VALUE)

    try:
        async with SessionLocal() as session:
            session.add(
                Organization(
                    id=org_id,
                    name="GS12 Owned Write Failure",
                    slug=f"gs12-owned-write-fail-{suffix}",
                    plan="test",
                    status="active",
                )
            )
            await session.flush()
            session.add(
                User(
                    id=owner_id,
                    organization_id=org_id,
                    email=actor.email,
                    name=actor.name,
                    password_hash="unused",
                    status="active",
                    auth_version=1,
                )
            )
            await session.flush()
            pilot = await pilots.create_pilot(
                session,
                actor,
                {
                    "organization_id": org_id,
                    "provider": "meta",
                    "provider_scope": "managed_ad_account",
                    "scope_ref": scope_ref,
                    "mode": "live_spend",
                    "owner_approval_reference": "gs12-owned-write-failure-test",
                },
            )
            await pilots.authorize_no_spend_write_validation(
                session,
                actor,
                pilot.id,
                reference="approvalref://single-use-token-read-failure",
            )
            pilot_id = pilot.id
            await session.commit()

        monkeypatch.setattr(
            owned_write.meta_owned,
            "_read_token",
            lambda _path: (_ for _ in ()).throw(
                owned_write.MetaOwnedWriteValidationError("test-token-read-failed")
            ),
        )
        with pytest.raises(
            owned_write.MetaOwnedWriteValidationError,
            match="test-token-read-failed",
        ):
            await owned_write.validate_and_record(pilot_id)

        async with SessionLocal() as session:
            pilot = await session.get(pilots.GrowthControlledPilot, pilot_id)
            assert pilot is not None
            approval = dict(pilot.evidence[pilots.NO_SPEND_WRITE_APPROVAL_EVIDENCE_KEY])
            assert approval["approved"] is True
            assert approval["consumed"] is True
            assert approval["completed"] is False
            assert approval["provider_call_executed"] is False
            assert approval["spend_executed"] is False
            assert pilot.legal_policy_acknowledged is False
            assert pilot.real_spend_allowed is False

        monkeypatch.setattr(
            owned_write.meta_owned,
            "_read_token",
            lambda _path: (_ for _ in ()).throw(
                AssertionError("consumed approval must fail before token read")
            ),
        )
        with pytest.raises(
            owned_write.MetaOwnedWriteValidationError,
            match="meta-owned-write-no-spend-approval-consumed",
        ):
            await owned_write.validate_and_record(pilot_id)
    finally:
        if pilot_id is not None:
            async with SessionLocal() as session:
                await session.execute(
                    delete(AuditEvent).where(AuditEvent.resource_id == pilot_id)
                )
                organization = await session.get(Organization, org_id)
                if organization is not None:
                    await session.delete(organization)
                await session.commit()
