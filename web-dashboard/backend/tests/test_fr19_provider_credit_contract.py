"""FR-19A cost/balance provenance and early-warning contracts.

These tests are deliberately provider-free and DB-free. They verify the
classification/redaction contract without reading credentials or spending money.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.services import provider_credit_alerts as credit


def _snapshot(*, mode: str, remaining: int = 4_000_000) -> credit.ProviderCreditSnapshot:
    return credit.ProviderCreditSnapshot(
        provider_id="provider-fr19",
        provider_type="synthetic-provider",
        enabled=True,
        funded_microusd=10_000_000,
        baseline_spend_microusd=2_000_000,
        current_spend_microusd=8_000_000,
        consumed_since_topup_microusd=6_000_000,
        remaining_microusd=remaining,
        low_threshold_microusd=5_000_000,
        critical_threshold_microusd=1_000_000,
        policy_version=7,
        funding_mode=mode,
    )


@pytest.mark.asyncio
async def test_measured_spend_uses_actual_route_spend_plus_recorded_runtime_spend() -> None:
    captured: list[Any] = []

    class FakeSession:
        async def scalar(self, statement: Any) -> int:
            captured.append(statement)
            return 2_500_000

    provider = SimpleNamespace(
        id="provider-fr19",
        config={"runtime_spend_microusd": 1_250_000},
    )

    measured = await credit.provider_total_spend_microusd(FakeSession(), provider)

    assert measured == 3_750_000
    assert len(captured) == 1
    rendered = str(captured[0])
    assert "actual_microusd" in rendered
    assert "estimated_microusd" not in rendered


def test_owner_attested_never_becomes_an_invented_numeric_balance() -> None:
    snapshot = _snapshot(mode="owner_attested", remaining=-6_000_000)

    public = snapshot.public()
    owner = snapshot.owner()

    assert snapshot.state == "funded_attested"
    for payload in (public, owner):
        assert payload["funding_mode"] == "owner_attested"
        assert payload["balance_amount_private"] is True
        assert payload["funded_usd"] is None
        assert payload["remaining_usd"] is None
        assert payload["low_balance_threshold_usd"] is None
        assert payload["critical_balance_threshold_usd"] is None
        assert payload["billing_failure_alerts_enabled"] is True


def test_numeric_private_keeps_public_amounts_private_but_owner_can_monitor_thresholds() -> None:
    snapshot = _snapshot(mode="numeric_private", remaining=900_000)

    public = snapshot.public()
    owner = snapshot.owner()

    assert snapshot.state == "critical"
    assert public["funded_usd"] is None
    assert public["remaining_usd"] is None
    assert public["low_balance_threshold_usd"] is None
    assert public["critical_balance_threshold_usd"] is None
    assert owner["funded_usd"] == 10.0
    assert owner["remaining_usd"] == 0.9
    assert owner["low_balance_threshold_usd"] == 5.0
    assert owner["critical_balance_threshold_usd"] == 1.0


@pytest.mark.asyncio
async def test_private_low_balance_warning_redacts_amount_from_message_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def notify_audience(*args: Any, **kwargs: Any) -> list[str]:
        del args
        calls.append(kwargs)
        return ["queued"]

    monkeypatch.setattr(credit.communications, "notify_audience", notify_audience)
    monkeypatch.setattr(credit, "owner_alert_channels", lambda: ["in_app"])

    result = await credit._notify_credit_state(
        SimpleNamespace(), _snapshot(mode="numeric_private", remaining=4_000_000)
    )

    assert result == ["queued"]
    assert len(calls) == 1
    call = calls[0]
    assert call["event_key"] == "project_ai.provider_credit.low"
    assert call["severity"] == "warning"
    assert "$" not in call["message"]
    assert call["payload"]["balance_amount_private"] is True
    assert call["payload"]["remaining_usd"] is None


@pytest.mark.asyncio
async def test_owner_attested_gets_predictive_gap_warning_without_fake_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def notify_audience(*args: Any, **kwargs: Any) -> list[str]:
        del args
        calls.append(kwargs)
        return ["queued"]

    monkeypatch.setattr(credit.communications, "notify_audience", notify_audience)
    monkeypatch.setattr(credit, "owner_alert_channels", lambda: ["in_app"])

    result = await credit._notify_predictive_monitoring_gap(
        SimpleNamespace(), _snapshot(mode="owner_attested")
    )

    assert result == ["queued"]
    assert len(calls) == 1
    call = calls[0]
    assert (
        call["event_key"]
        == "project_ai.provider_credit.predictive_monitoring_required"
    )
    assert call["payload"]["funded_usd"] is None
    assert call["payload"]["remaining_usd"] is None
    assert "numeric funded amount" in call["message"]


@pytest.mark.asyncio
async def test_billing_failure_alert_does_not_require_or_expose_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    provider = SimpleNamespace(
        id="provider-fr19",
        type="synthetic-provider",
        organization_id="org-fr19",
    )

    class FakeSession:
        async def get(self, model: Any, provider_id: str) -> Any:
            del model
            assert provider_id == provider.id
            return provider

    async def notify_audience(*args: Any, **kwargs: Any) -> list[str]:
        del args
        calls.append(kwargs)
        return ["queued"]

    monkeypatch.setattr(credit.communications, "notify_audience", notify_audience)
    monkeypatch.setattr(credit, "owner_alert_channels", lambda: ["in_app"])

    result = await credit.notify_provider_billing_failure(
        FakeSession(),
        provider_id=provider.id,
        failure_code="billing_required",
        critical=True,
    )

    assert result == ["queued"]
    assert len(calls) == 1
    call = calls[0]
    assert call["event_key"] == "project_ai.provider_billing.action_required"
    assert call["severity"] == "critical"
    assert call["payload"] == {
        "provider_id": provider.id,
        "provider_type": provider.type,
        "failure_code": "billing_required",
    }
    assert "remaining_usd" not in call["payload"]
    assert "funded_usd" not in call["payload"]
