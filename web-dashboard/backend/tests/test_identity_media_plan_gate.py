"""Identity media (face and voice) runs paid provider jobs: Business plan only, 5 per organization per day.

Owner decision 2026-11-27, taken before the routes open on the public gateway.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints import identity_media as endpoint
from app.core.auth import auth_service
from app.db.base import SessionLocal
from app.db.models import IdentityMediaExecution
from app.db.seed import seed
from app.services import billing


async def _user(session, suffix: str):
    return await auth_service.register(
        session,
        email=f"identity-gate-{suffix}@example.com",
        password=f"Strong!{suffix}",
        name="Identity Gate",
        organization_name=f"Identity Gate {suffix}",
    )


def _execution(actor, key: str) -> IdentityMediaExecution:
    return IdentityMediaExecution(
        organization_id=actor.organization_id,
        user_id=actor.id,
        operation="voice_clone",
        identity_basis="self",
        provider_access="paid",
        model="minimax/voice-cloning",
        idempotency_key=key,
        subject_reference="me",
    )


@pytest.mark.asyncio
async def test_business_is_the_only_plan_with_identity_media() -> None:
    await seed()
    async with SessionLocal() as session:
        catalog = await billing.sync_catalog(session)
        await session.commit()
    by_code = {plan["code"]: plan for plan in catalog["plans"]}
    assert "identity.media" in by_code["business"]["entitlements"]
    for code in ("free", "professional", "premium"):
        if code in by_code:
            assert "identity.media" not in by_code[code]["entitlements"], code


@pytest.mark.asyncio
async def test_a_plan_without_the_entitlement_is_refused_before_any_upload() -> None:
    await seed()
    suffix = uuid4().hex
    async with SessionLocal() as session:
        actor = await _user(session, suffix)
        assert await endpoint._plan_entitled(session, actor) is False
        with pytest.raises(HTTPException) as refused:
            await endpoint._require_plan(session, actor)
        assert refused.value.status_code == 402
        assert refused.value.detail["entitlement"] == "identity.media"


@pytest.mark.asyncio
async def test_the_sixth_run_in_a_day_is_refused_but_a_retry_of_the_same_request_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await seed()
    monkeypatch.setattr(endpoint.settings, "IDENTITY_MEDIA_DAILY_EXECUTIONS_PER_ORG", 5)
    suffix = uuid4().hex
    async with SessionLocal() as session:
        actor = await _user(session, suffix)
        for index in range(5):
            await endpoint._require_daily_room(session, actor, f"key-{index}-{suffix}")
            session.add(_execution(actor, f"key-{index}-{suffix}"))
            await session.commit()
        assert await endpoint._executions_today(session, actor.organization_id) == 5

        with pytest.raises(HTTPException) as blocked:
            await endpoint._require_daily_room(session, actor, f"key-new-{suffix}")
        assert blocked.value.status_code == 429
        assert blocked.value.detail == {"code": "IDENTITY_MEDIA_DAILY_LIMIT", "limit": 5}
        await session.rollback()

        # Re-sending request 0 (same idempotency key) returns the existing run, so it is not counted.
        await endpoint._require_daily_room(session, actor, f"key-0-{suffix}")
        await session.rollback()
