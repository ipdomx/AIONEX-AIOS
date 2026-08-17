"""Phase 36C provider credit monitoring and Owner escalation contracts."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.db.base import SessionLocal
from app.db.models import AIProvider, Organization, OwnerControlRecord
from app.services import communications
from app.services.provider_credit_alerts import (
    PROVIDER_FINANCE_DOMAIN,
    ProviderCreditPolicyError,
    configure_provider_credit,
    notify_provider_billing_failure,
    provider_credit_snapshot,
    run_provider_credit_alerts,
)


async def _seed_provider(*, runtime_spend_microusd: int = 0) -> str:
    suffix = uuid4().hex[:10]
    provider_id = f"credit-provider-{suffix}"
    async with SessionLocal() as session:
        await session.execute(
            delete(OwnerControlRecord).where(
                OwnerControlRecord.domain == PROVIDER_FINANCE_DOMAIN
            )
        )
        await session.execute(delete(AIProvider).where(AIProvider.id.like("credit-provider-%")))
        await session.commit()
        platform = await session.get(Organization, "aionex-org")
        if platform is None:
            session.add(Organization(
                id="aionex-org",
                name="AIONEX Platform",
                slug=f"aionex-credit-platform-{suffix}",
                plan="enterprise",
                status="active",
            ))
            await session.flush()
        session.add(AIProvider(
            id=provider_id,
            organization_id="aionex-org",
            name="Credit Test Provider",
            type="groq",
            status="connected",
            base_url="https://api.groq.com/openai",
            encrypted_api_key=None,
            config={
                "enabled": True,
                "runtime_spend_microusd": runtime_spend_microusd,
            },
        ))
        await session.commit()
    return provider_id


@pytest.mark.asyncio
async def test_credit_snapshot_tracks_spend_since_owner_topup_baseline() -> None:
    provider_id = await _seed_provider(runtime_spend_microusd=1_000_000)
    async with SessionLocal() as session:
        initial = await configure_provider_credit(
            session,
            provider_id=provider_id,
            funded_credit_usd=10.0,
            low_balance_threshold_usd=3.0,
            critical_balance_threshold_usd=1.0,
        )
        assert initial.remaining_usd == 10.0
        provider = await session.get(AIProvider, provider_id)
        assert provider is not None
        config = dict(provider.config or {})
        config["runtime_spend_microusd"] = 8_500_000
        provider.config = config
        await session.commit()

    async with SessionLocal() as session:
        snapshot = await provider_credit_snapshot(session, provider_id=provider_id)
        assert snapshot.consumed_since_topup_microusd == 7_500_000
        assert snapshot.remaining_usd == 2.5
        assert snapshot.state == "low"


@pytest.mark.asyncio
async def test_credit_policy_rejects_thresholds_above_funded_balance() -> None:
    provider_id = await _seed_provider()
    async with SessionLocal() as session:
        with pytest.raises(ProviderCreditPolicyError, match="cannot exceed funded credit"):
            await configure_provider_credit(
                session,
                provider_id=provider_id,
                funded_credit_usd=5.0,
                low_balance_threshold_usd=6.0,
                critical_balance_threshold_usd=1.0,
            )


@pytest.mark.asyncio
async def test_periodic_low_credit_alert_uses_platform_owner_audience(monkeypatch) -> None:
    provider_id = await _seed_provider()
    async with SessionLocal() as session:
        await configure_provider_credit(
            session,
            provider_id=provider_id,
            funded_credit_usd=10.0,
            low_balance_threshold_usd=3.0,
            critical_balance_threshold_usd=1.0,
        )
        await session.commit()
        provider = await session.get(AIProvider, provider_id)
        assert provider is not None
        config = dict(provider.config or {})
        config["runtime_spend_microusd"] = 8_000_000
        provider.config = config
        await session.commit()

    captured: list[dict] = []

    async def fake_notify_audience(_session, **kwargs):
        captured.append(kwargs)
        return ["notification"]

    monkeypatch.setattr(communications, "notify_audience", fake_notify_audience)
    async with SessionLocal() as session:
        notifications = await run_provider_credit_alerts(session)
        assert notifications == ["notification"]
    match = next(row for row in captured if row.get("source_id") == provider_id)
    assert match["audience"] == "platform_owner"
    assert match["severity"] == "warning"
    assert match["event_key"] == "project_ai.provider_credit.low"
    assert match["payload"]["remaining_usd"] == 2.0


@pytest.mark.asyncio
async def test_billing_failure_immediately_escalates_without_provider_payload(monkeypatch) -> None:
    provider_id = await _seed_provider()
    captured: list[dict] = []

    async def fake_notify_audience(_session, **kwargs):
        captured.append(kwargs)
        return ["critical"]

    monkeypatch.setattr(communications, "notify_audience", fake_notify_audience)
    async with SessionLocal() as session:
        rows = await notify_provider_billing_failure(
            session,
            provider_id=provider_id,
            failure_code="billing_required",
            critical=True,
        )
        assert rows == ["critical"]
    assert captured[0]["audience"] == "platform_owner"
    assert captured[0]["severity"] == "critical"
    assert captured[0]["payload"] == {
        "provider_id": provider_id,
        "provider_type": "groq",
        "failure_code": "billing_required",
    }


@pytest.mark.asyncio
async def test_finance_policy_record_is_owner_control_not_provider_secret_state() -> None:
    provider_id = await _seed_provider()
    async with SessionLocal() as session:
        await configure_provider_credit(
            session,
            provider_id=provider_id,
            funded_credit_usd=20,
            low_balance_threshold_usd=5,
            critical_balance_threshold_usd=2,
        )
        await session.commit()
        record = await session.scalar(
            select(OwnerControlRecord).where(
                OwnerControlRecord.domain == PROVIDER_FINANCE_DOMAIN,
                OwnerControlRecord.resource_id == provider_id,
            )
        )
        assert record is not None
        assert set(record.payload) == {
            "funded_microusd",
            "baseline_spend_microusd",
            "low_threshold_microusd",
            "critical_threshold_microusd",
            "topup_recorded_at",
        }
