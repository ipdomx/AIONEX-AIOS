from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import growth_access


class _FakeSession:
    pass


def _actor(*, status="active"):
    return SimpleNamespace(
        id="user-1",
        organization_id="org-1",
        status=status,
    )


@pytest.mark.asyncio
async def test_unknown_capability_is_denied(monkeypatch):
    decision = await growth_access.effective_access(_FakeSession(), _actor(), "unknown")  # type: ignore[arg-type]
    assert decision.allowed is False
    assert decision.reason == "unknown-capability"


@pytest.mark.asyncio
async def test_inactive_user_is_denied_before_billing(monkeypatch):
    async def boom(*_args, **_kwargs):
        raise AssertionError("billing must not be called")

    monkeypatch.setattr(growth_access.billing, "billing_context", boom)
    decision = await growth_access.effective_access(_FakeSession(), _actor(status="suspended"), "campaign.research")  # type: ignore[arg-type]
    assert decision.allowed is False
    assert decision.reason == "user-inactive"


@pytest.mark.asyncio
async def test_owner_deny_wins_over_plan_entitlement(monkeypatch):
    async def billing_context(*_args, **_kwargs):
        return {
            "account": SimpleNamespace(status="active"),
            "entitlements": ["growth.campaign.research"],
        }

    async def override(_session, scope, subject_id, capability):
        if scope == "user":
            return SimpleNamespace(
                enabled=True,
                payload={"allowed": False, "approval_required": False, "limits": {}},
            )
        return None

    monkeypatch.setattr(growth_access.billing, "billing_context", billing_context)
    monkeypatch.setattr(growth_access, "_override", override)
    decision = await growth_access.effective_access(_FakeSession(), _actor(), "campaign.research")  # type: ignore[arg-type]
    assert decision.allowed is False
    assert decision.source == "owner-override"
    assert decision.reason == "owner-deny"


@pytest.mark.asyncio
async def test_owner_grant_can_enable_free_user_without_plan_entitlement(monkeypatch):
    async def billing_context(*_args, **_kwargs):
        return {"account": SimpleNamespace(status="active"), "entitlements": []}

    async def override(_session, scope, subject_id, capability):
        if scope == "user":
            return SimpleNamespace(
                enabled=True,
                payload={
                    "allowed": True,
                    "approval_required": True,
                    "limits": {"monthly_campaigns": 2},
                },
            )
        return None

    monkeypatch.setattr(growth_access.billing, "billing_context", billing_context)
    monkeypatch.setattr(growth_access, "_override", override)
    decision = await growth_access.effective_access(_FakeSession(), _actor(), "ads.manage")  # type: ignore[arg-type]
    assert decision.allowed is True
    assert decision.approval_required is True
    assert decision.limits == {"monthly_campaigns": 2}


@pytest.mark.asyncio
async def test_plan_entitlement_applies_without_override(monkeypatch):
    async def billing_context(*_args, **_kwargs):
        return {
            "account": SimpleNamespace(status="active"),
            "entitlements": ["growth.analytics.read"],
        }

    async def override(*_args, **_kwargs):
        return None

    monkeypatch.setattr(growth_access.billing, "billing_context", billing_context)
    monkeypatch.setattr(growth_access, "_override", override)
    decision = await growth_access.effective_access(_FakeSession(), _actor(), "analytics.read")  # type: ignore[arg-type]
    assert decision.allowed is True
    assert decision.source == "plan-entitlement"


@pytest.mark.asyncio
async def test_owner_grant_with_unsafe_legacy_limits_fails_closed_without_reflection(
    monkeypatch,
):
    async def billing_context(*_args, **_kwargs):
        return {"account": SimpleNamespace(status="active"), "entitlements": []}

    async def override(_session, scope, subject_id, capability):
        if scope == "user":
            return SimpleNamespace(
                enabled=True,
                payload={
                    "allowed": True,
                    "approval_required": False,
                    "limits": {"access_token": "legacy-secret-must-not-return"},
                },
            )
        return None

    monkeypatch.setattr(growth_access.billing, "billing_context", billing_context)
    monkeypatch.setattr(growth_access, "_override", override)
    decision = await growth_access.effective_access(
        _FakeSession(), _actor(), "ads.manage"
    )  # type: ignore[arg-type]

    assert decision.allowed is False
    assert decision.source == "owner-override"
    assert decision.reason == "owner-override-invalid-limits"
    assert decision.approval_required is True
    assert decision.limits == {}
    assert "legacy-secret-must-not-return" not in repr(decision.as_dict())


@pytest.mark.asyncio
async def test_owner_deny_with_unsafe_legacy_limits_stays_denied_without_reflection(
    monkeypatch,
):
    async def billing_context(*_args, **_kwargs):
        return {
            "account": SimpleNamespace(status="active"),
            "entitlements": ["growth.ads.manage"],
        }

    async def override(_session, scope, subject_id, capability):
        if scope == "user":
            return SimpleNamespace(
                enabled=True,
                payload={
                    "allowed": False,
                    "approval_required": False,
                    "limits": {"secret": "legacy-deny-secret-must-not-return"},
                },
            )
        return None

    monkeypatch.setattr(growth_access.billing, "billing_context", billing_context)
    monkeypatch.setattr(growth_access, "_override", override)
    decision = await growth_access.effective_access(
        _FakeSession(), _actor(), "ads.manage"
    )  # type: ignore[arg-type]

    assert decision.allowed is False
    assert decision.reason == "owner-deny"
    assert decision.limits == {}
    assert "legacy-deny-secret-must-not-return" not in repr(decision.as_dict())
