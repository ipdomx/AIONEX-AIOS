from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import external_activation_gates as gates


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return list(self._values)


class _Session:
    def __init__(self, responses):
        self._responses = iter(responses)

    async def scalars(self, _statement):
        return _Scalars(next(self._responses))


def test_external_gate_catalog_matches_phase36_registry_exactly() -> None:
    assert gates.catalog_invariant() == {
        "missing_definitions": [],
        "orphan_definitions": [],
    }


@pytest.mark.asyncio
async def test_snapshot_excludes_store_scope_and_keeps_other_external_facts_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gates.billing,
        "provider_readiness",
        lambda: [
            {
                "id": "stripe",
                "configured": True,
                "status": "ready",
                "mode": "live",
                "capabilities": ["checkout"],
            }
        ],
    )
    provider = SimpleNamespace(id="provider-openai", type="openai")
    session = _Session([[provider], []])
    snapshot = await gates.external_activation_snapshot(session)  # type: ignore[arg-type]
    by_id = {item["gate_id"]: item for item in snapshot["gates"]}

    assert by_id["store-signing-and-publication"]["status"] == "excluded_current_scope"
    assert by_id["live-payment-provider-credential"]["status"] == "satisfied_runtime"
    assert by_id["owner-provider-funded-credit-thresholds"]["status"] == "blocked_external"
    assert by_id["public-stun-turn-and-sfu-capacity"]["status"] == "blocked_external"
    assert by_id["music-rights-and-ai-generated-disclosure"]["status"] == (
        "enforced_internal_external_pending"
    )
    assert snapshot["scope_policy"]["direct_apple_pay_excluded"] is True
    assert snapshot["catalog_invariant"]["missing_definitions"] == []


@pytest.mark.asyncio
async def test_provider_finance_gate_satisfies_only_when_every_connected_launch_provider_has_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gates.billing,
        "provider_readiness",
        lambda: [],
    )
    provider = SimpleNamespace(id="provider-openai", type="openai")
    session = _Session([[provider], ["provider-openai"]])
    snapshot = await gates.external_activation_snapshot(session)  # type: ignore[arg-type]
    by_id = {item["gate_id"]: item for item in snapshot["gates"]}
    finance = by_id["owner-provider-funded-credit-thresholds"]
    assert finance["status"] == "satisfied_runtime"
    assert finance["live_evidence"]["configured_finance_records"] == 1
    assert finance["live_evidence"]["missing_provider_types"] == []


def test_owner_router_registers_read_only_external_activation_endpoint() -> None:
    repo = Path(__file__).resolve().parents[3]
    source = (repo / "web-dashboard/backend/app/api/v1/router.py").read_text(encoding="utf-8")
    endpoint = (repo / "web-dashboard/backend/app/api/owner/external_activation.py").read_text(encoding="utf-8")
    assert "owner_external_activation.router" in source
    assert '@router.get("")' in endpoint
    assert "@router.post" not in endpoint
    assert "@router.put" not in endpoint
    assert "@router.delete" not in endpoint
