from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import growth_access


@pytest.mark.asyncio
async def test_gs01_deterministic_access_simulation(monkeypatch):
    state = {
        "user-free": {"entitlements": [], "override": True, "status": "active"},
        "user-paid": {"entitlements": ["growth.ads.manage"], "override": None, "status": "active"},
        "user-revoked": {"entitlements": ["growth.ads.manage"], "override": True, "status": "active"},
    }

    async def billing_context(_session, organization_id):
        user_id = organization_id.replace("org-", "user-")
        data = state[user_id]
        return {
            "account": SimpleNamespace(status="active"),
            "entitlements": data["entitlements"],
        }

    async def override(_session, scope, subject_id, capability):
        if scope != "user":
            return None
        data = state[subject_id]
        if data["override"] is None:
            return None
        return SimpleNamespace(
            enabled=True,
            payload={
                "allowed": bool(data["override"]),
                "approval_required": True,
                "limits": {"daily_spend_minor": 0},
            },
        )

    monkeypatch.setattr(growth_access.billing, "billing_context", billing_context)
    monkeypatch.setattr(growth_access, "_override", override)

    def actor(user_id):
        return SimpleNamespace(
            id=user_id,
            organization_id=user_id.replace("user-", "org-"),
            status=state[user_id]["status"],
        )

    free = await growth_access.effective_access(None, actor("user-free"), "ads.manage")  # type: ignore[arg-type]
    paid = await growth_access.effective_access(None, actor("user-paid"), "ads.manage")  # type: ignore[arg-type]
    revoked = await growth_access.effective_access(None, actor("user-revoked"), "ads.manage")  # type: ignore[arg-type]

    assert free.allowed is True
    assert free.source == "owner-override"
    assert free.limits["daily_spend_minor"] == 0
    assert paid.allowed is True  # paid entitlement applies with no owner override
    assert revoked.allowed is True

    state["user-revoked"]["override"] = False
    immediately_revoked = await growth_access.effective_access(None, actor("user-revoked"), "ads.manage")  # type: ignore[arg-type]
    assert immediately_revoked.allowed is False
    assert immediately_revoked.reason == "owner-deny"
