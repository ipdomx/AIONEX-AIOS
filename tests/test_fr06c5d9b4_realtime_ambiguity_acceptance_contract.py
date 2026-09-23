"""Source contract for FR-06C5D9B4 Realtime ambiguity acceptance."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_ambiguity_acceptance.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B4-realtime-ambiguity-acceptance.md"


def _calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_ambiguity_acceptance_source"]


def test_ambiguity_acceptance_is_read_only_and_uses_durable_drain_snapshot():
    text = SERVICE.read_text()
    assert "measure_realtime_drain" in text
    assert "submitted_provider_ids" in text
    assert "active_provider_ids" in text
    assert "unresolved_provider_ids" in text
    assert "expired_unsettled_session_ids" in text
    assert "legacy_ambiguous_recording_ids" in text
    assert "durable_realtime_blockers_present" in text
    calls = _calls(SERVICE)
    forbidden = (
        ".commit", ".rollback", ".add", ".delete", ".unlink", ".remove",
        ".replace", ".rename", "collect_livekit_provider_inventory",
        "evaluate_realtime_turn_boundary",
    )
    assert not any(call.endswith(forbidden) for call in calls)
    assert "livekit_runtime" not in text


def test_ambiguity_acceptance_never_authorizes_retry_adoption_rollout_or_drain_claims():
    text = SERVICE.read_text()
    for marker in (
        "provider_io_performed: bool = False",
        "automatic_settlement: bool = False",
        "automatic_retry: bool = False",
        "automatic_adoption: bool = False",
        "production_database_migrated: bool = False",
        "migration_0064_rollout_allowed: bool = False",
        "provider_drain_verified: bool = False",
        "full_host_closure: bool = False",
    ):
        assert marker in text
    assert "RealtimeAmbiguityAcceptanceBlocked" in text


def test_plan_advances_to_d9b4_without_production_or_full_drain_claim():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B4"
    assert item["source_part"] == "FR-06C5D9B4"
    assert item["prerequisite_source_part"] == "FR-06C5D9B3D"
    assert item["provider_ambiguity_blocks_rollout"] is True
    assert item["legacy_ambiguous_recording_blocks_rollout"] is True
    assert item["expired_unsettled_session_blocks_rollout"] is True
    assert item["provider_io_performed"] is False
    assert item["automatic_settlement"] is False
    assert item["automatic_retry"] is False
    assert item["automatic_adoption"] is False
    assert item["production_database_migrated"] is False
    assert item["migration_0064_rollout_allowed"] is False
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()
