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
    session = _Session([[provider], [], []])
    snapshot = await gates.external_activation_snapshot(session)  # type: ignore[arg-type]
    by_id = {item["gate_id"]: item for item in snapshot["gates"]}

    assert by_id["store-signing-and-publication"]["status"] == "excluded_current_scope"
    assert by_id["live-payment-provider-credential"]["status"] == "satisfied_runtime"
    assert by_id["owner-provider-funded-credit-thresholds"]["status"] == "blocked_external"
    assert by_id["public-stun-turn-and-sfu-capacity"]["status"] == "satisfied_runtime"
    assert by_id["provider-rendered-podcast-jingle-runtime-evidence"]["status"] == "satisfied_runtime"
    assert by_id["explicit-consent-egress-runtime-acceptance"]["status"] == "satisfied_runtime"
    assert by_id["recording-retention-and-studio-ingestion-runtime-evidence"]["status"] == "satisfied_runtime"
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
    session = _Session([[provider], ["provider-openai"], []])
    snapshot = await gates.external_activation_snapshot(session)  # type: ignore[arg-type]
    by_id = {item["gate_id"]: item for item in snapshot["gates"]}
    finance = by_id["owner-provider-funded-credit-thresholds"]
    assert finance["status"] == "satisfied_runtime"
    assert finance["live_evidence"]["configured_finance_records"] == 1
    assert finance["live_evidence"]["missing_provider_types"] == []


def test_owner_router_registers_governed_external_activation_evidence_workflow() -> None:
    repo = Path(__file__).resolve().parents[3]
    source = (repo / "web-dashboard/backend/app/api/v1/router.py").read_text(encoding="utf-8")
    endpoint = (repo / "web-dashboard/backend/app/api/owner/external_activation.py").read_text(encoding="utf-8")
    assert "owner_external_activation.router" in source
    assert '@router.get("")' in endpoint
    assert '@router.post("/{gate_id}/evidence"' in endpoint
    assert '@router.put("/{gate_id}/evidence/review")' in endpoint
    assert '"runtime_gate_override": False' in endpoint
    assert "@router.delete" not in endpoint


def test_realtime_runtime_receipt_checksum_is_immutable_and_matches_source() -> None:
    import hashlib

    repo = Path(__file__).resolve().parents[3]
    receipt = repo / gates.REALTIME_ACCEPTANCE_RECEIPT_PATH
    assert receipt.exists()
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == gates.REALTIME_ACCEPTANCE_RECEIPT_SHA256
    closeout = repo / gates.PRE_XR_RUNTIME_CLOSEOUT_RECEIPT_PATH
    assert closeout.exists()
    assert hashlib.sha256(closeout.read_bytes()).hexdigest() == gates.PRE_XR_RUNTIME_CLOSEOUT_RECEIPT_SHA256
    assert set(gates.RUNTIME_RECEIPT_EVIDENCE) == {
        "explicit-consent-egress-runtime-acceptance",
        "public-stun-turn-and-sfu-capacity",
        "provider-rendered-podcast-jingle-runtime-evidence",
        "recording-retention-and-studio-ingestion-runtime-evidence",
    }


@pytest.mark.asyncio
async def test_accepted_owner_evidence_satisfies_only_reviewable_external_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gates.billing, "provider_readiness", lambda: [])
    provider = SimpleNamespace(id="provider-openai", type="openai")
    evidence = SimpleNamespace(
        resource_id="music-rights-and-ai-generated-disclosure",
        enabled=True,
        status="active",
        version=3,
        payload={
            "review_status": "accepted",
            "evidence_reference": "owner-vault://music-license/2026",
            "evidence_sha256": "a" * 64,
            "issuer": "External Rights Authority",
            "expires_at": None,
            "submitted_at": "2026-09-07T00:00:00+00:00",
            "reviewed_at": "2026-09-07T00:05:00+00:00",
            "review_note": "Verified against external authority.",
        },
    )
    session = _Session([[provider], [], [evidence]])
    snapshot = await gates.external_activation_snapshot(session)  # type: ignore[arg-type]
    by_id = {item["gate_id"]: item for item in snapshot["gates"]}
    music = by_id["music-rights-and-ai-generated-disclosure"]
    assert music["status"] == "satisfied_external_evidence"
    assert music["owner_evidence_reviewable"] is True
    assert music["owner_evidence"]["evidence_sha256"] == "a" * 64
    assert by_id["provider-rendered-podcast-jingle-runtime-evidence"][
        "owner_evidence_reviewable"
    ] is False


class _MutationSession:
    def __init__(self, scalar_value=None):
        self.scalar_value = scalar_value
        self.added = []

    async def scalar(self, _statement):
        return self.scalar_value

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None


@pytest.mark.asyncio
async def test_runtime_derived_gate_rejects_manual_owner_evidence_transition() -> None:
    session = _MutationSession()
    with pytest.raises(
        gates.ExternalActivationEvidenceError,
        match="runtime-derived",
    ):
        await gates.submit_owner_evidence(
            session,  # type: ignore[arg-type]
            gate_id="provider-rendered-podcast-jingle-runtime-evidence",
            actor_id="owner-1",
            evidence_reference="vault://must-not-override-runtime",
            evidence_sha256="a" * 64,
            issuer="Owner",
        )
    assert session.added == []


@pytest.mark.asyncio
async def test_reviewable_owner_evidence_is_versioned_and_requires_review() -> None:
    session = _MutationSession()
    submitted = await gates.submit_owner_evidence(
        session,  # type: ignore[arg-type]
        gate_id="music-rights-and-ai-generated-disclosure",
        actor_id="owner-1",
        evidence_reference="vault://rights/license-2026",
        evidence_sha256="b" * 64,
        issuer="Rights Authority",
        notes="Bounded commercial-use evidence",
    )
    assert submitted["review_status"] == "submitted"
    assert submitted["version"] == 1
    assert len(session.added) == 1

    record = session.added[0]
    session.scalar_value = record
    reviewed = await gates.review_owner_evidence(
        session,  # type: ignore[arg-type]
        gate_id="music-rights-and-ai-generated-disclosure",
        actor_id="owner-1",
        decision="accepted",
        review_note="Checksum and issuer reviewed.",
    )
    assert reviewed["review_status"] == "accepted"
    assert reviewed["version"] == 2
    assert reviewed["evidence_sha256"] == "b" * 64
