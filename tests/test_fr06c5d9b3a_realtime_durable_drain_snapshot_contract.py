"""Source contract for FR-06C5D9B3A durable Realtime drain measurement."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAIN = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_drain.py"
LEDGER = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_resources.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B3A-realtime-durable-drain-snapshot.md"


def _calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_durable_drain_snapshot_source"]


def test_snapshot_is_read_only_repeatable_read_and_closed_authority_bound():
    text = DRAIN.read_text()
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" in text
    assert 'required_scope=_SCOPE' in text
    assert "authority.is_open or authority.operation_id is None" in text
    assert "item.admitted_generation >= authority.generation" in text
    assert "item.admitted_operation_id == authority.operation_id" in text
    calls = _calls(DRAIN)
    forbidden = (".commit", ".rollback", ".add", ".delete", ".unlink", ".remove", ".replace", ".rename")
    assert not any(call.endswith(forbidden) for call in calls)
    assert "livekit_runtime" not in text


def test_snapshot_reports_durable_and_legacy_blockers_without_provider_claims():
    text = DRAIN.read_text()
    for field in (
        "unfinished_provider_ids", "unresolved_provider_ids", "expired_unsettled_session_ids",
        "active_room_ids", "connected_participant_ids", "provider_recording_ids",
        "legacy_unowned_room_ids", "legacy_unowned_session_grant_ids",
        "legacy_unowned_egress_recording_ids", "legacy_unowned_file_recording_ids",
        "legacy_ambiguous_recording_ids",
    ):
        assert field in text
    assert "coverage_unverified: bool = True" in text
    assert "live_provider_inventory_verified: bool = False" in text
    assert "connected_presence_provider_drain_verified: bool = False" in text
    assert "turn_allocation_drain_verified: bool = False" in text
    assert "provider_drain_verified: bool = False" in text
    assert "full_host_closure: bool = False" in text


def test_provider_observation_redacts_nonce_reason_and_reference_digest():
    text = LEDGER.read_text()
    assert "class RealtimeProviderResourceObservation" in text
    block = text[text.index("class RealtimeProviderResourceObservation"):text.index("def _uuid")]
    assert "nonce:" not in block
    assert "provider_ref_sha256:" not in block
    assert "unresolved_reason:" not in block
    assert "unresolved_reason_present" in block
    assert "provider_reference_present" in block


def test_plan_advances_to_d9b3a_without_claiming_provider_drain():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B4"
    assert item["source_part"] == "FR-06C5D9B3A"
    assert item["prerequisite_source_part"] == "FR-06C5D9B2B4"
    assert item["repeatable_read"] is True
    assert item["closed_authority_required"] is True
    assert item["provider_io_performed"] is False
    assert item["automatic_settlement"] is False
    assert item["connected_presence_provider_drain_verified"] is False
    assert item["turn_allocation_drain_verified"] is False
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()
