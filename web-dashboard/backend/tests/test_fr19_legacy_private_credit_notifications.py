"""FR19: historical private credit notifications redact on API/realtime reads.

These are synthetic value-object tests. No database, external delivery, paid
provider, credentials, network, or production state is used.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services import communications


PRIVATE_AMOUNTS = (
    "funded_usd",
    "consumed_since_topup_usd",
    "remaining_usd",
    "low_balance_threshold_usd",
    "critical_balance_threshold_usd",
    "funded_microusd",
    "baseline_spend_microusd",
    "current_spend_microusd",
    "consumed_since_topup_microusd",
    "remaining_microusd",
    "low_threshold_microusd",
    "critical_threshold_microusd",
)


def _old_notification(
    *,
    event: str = "project_ai.provider_credit.critical",
    funding_mode: str = "numeric_private",
    private: bool = True,
) -> SimpleNamespace:
    data: dict[str, Any] = {
        "funding_mode": funding_mode,
        "balance_amount_private": private,
        "funded_usd": 10.0,
        "consumed_since_topup_usd": 9.75,
        "remaining_usd": 0.25,
        "low_balance_threshold_usd": 3.0,
        "critical_balance_threshold_usd": 1.0,
        "funded_microusd": 10_000_000,
        "baseline_spend_microusd": 2_000_000,
        "current_spend_microusd": 11_750_000,
        "consumed_since_topup_microusd": 9_750_000,
        "remaining_microusd": 250_000,
        "low_threshold_microusd": 3_000_000,
        "critical_threshold_microusd": 1_000_000,
        "safe_label": "synthetic-owner-credit",
    }
    return SimpleNamespace(
        id="synthetic-notification", organization_id="synthetic-owner-org",
        recipient_id="synthetic-owner", type=event, category="billing",
        event_key=event, audience="platform_owner",
        title="Synthetic credit warning", message="No private balance shown",
        severity="warning", source_type="ai_provider",
        source_id="synthetic-provider", correlation_id="synthetic-provider",
        payload=data, read_at=None, archived_at=None,
        created_at=None, updated_at=None,
    )


@pytest.mark.parametrize(
    ("funding_mode", "private"),
    [("numeric_private", True), ("owner_attested", True),
     ("numeric_private", False), ("numeric", True)],
)
def test_historical_private_credit_amounts_not_replayed(
    funding_mode: str, private: bool,
) -> None:
    original = _old_notification(funding_mode=funding_mode, private=private)
    first = communications.notification_snapshot(original)
    second = communications.notification_snapshot(original)
    for key in PRIVATE_AMOUNTS:
        assert first["payload"][key] is None
        assert second["payload"][key] is None
    assert first["payload"]["safe_label"] == "synthetic-owner-credit"
    # Read-time protection must never mutate an ORM JSON payload in memory.
    assert original.payload["consumed_since_topup_usd"] == 9.75
    assert original.payload["funded_microusd"] == 10_000_000


def test_public_numeric_credit_preserves_observed_spending() -> None:
    original = _old_notification(funding_mode="numeric", private=False)
    snapshot = communications.notification_snapshot(original)
    assert snapshot["payload"]["consumed_since_topup_usd"] == 9.75
    assert snapshot["payload"]["remaining_usd"] == 0.25


def test_unrelated_notification_does_not_change_its_payload() -> None:
    original = _old_notification(
        event="system.generic", funding_mode="numeric_private", private=True
    )
    snapshot = communications.notification_snapshot(original)
    assert snapshot["payload"] == original.payload
    assert snapshot["payload"] is not original.payload


def test_realtime_event_uses_redacted_legacy_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _old_notification()
    published = AsyncMock()
    monkeypatch.setattr(communications.realtime_event_runtime, "publish", published)
    asyncio.run(communications.publish_realtime(original))
    published.assert_awaited_once()
    args = published.await_args.args
    assert args[0] == "synthetic-owner-org"
    event = args[1]
    assert event["type"] == "notification.created"
    payload = event["notification"]["payload"]
    assert payload["consumed_since_topup_usd"] is None
    assert payload["funded_microusd"] is None
    assert original.payload["consumed_since_topup_usd"] == 9.75
