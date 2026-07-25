from __future__ import annotations

from aios.cognitive import CognitiveCore
from aios.cognitive.models import DecisionStatus


def test_safe_proposal_reaches_quorum(tmp_path):
    core = CognitiveCore(tmp_path / "ledger.jsonl")
    outcome = core.decide("Add reporting module", "Create an isolated reporting module with tests", risk_level="low")
    assert outcome.quorum_reached is True
    assert outcome.status in {DecisionStatus.APPROVED, DecisionStatus.CONDITIONAL}
    assert len(outcome.opinions) == 10
    assert len(core.ledger.read_all()) == 1


def test_destructive_live_change_requires_human_approval(tmp_path):
    core = CognitiveCore(tmp_path / "ledger.jsonl")
    outcome = core.decide("Delete production data", "rm -rf production database", risk_level="critical")
    assert outcome.human_approval_required is True
    assert outcome.status in {DecisionStatus.CONDITIONAL, DecisionStatus.REJECTED}
    assert outcome.risks


def test_self_update_is_governed(tmp_path):
    core = CognitiveCore(tmp_path / "ledger.jsonl")
    outcome = core.decide("Self update", "Allow AIOS to self update in a sandbox", risk_level="high")
    assert outcome.human_approval_required is True
    assert "Run in an isolated environment" in outcome.conditions
