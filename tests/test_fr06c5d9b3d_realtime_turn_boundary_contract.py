"""Source contract for FR-06C5D9B3D TURN/Coturn drain boundary."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_turn_boundary.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B3D-realtime-turn-boundary.md"
PHASE36_RECEIPT = ROOT / "docs/phase-36/receipts/36H-2026-09-23-realtime-turn-boundary.md"


def _calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_turn_boundary_source"]


def test_turn_boundary_consumes_provider_inventory_but_never_claims_turn_drain():
    text = SERVICE.read_text()
    assert "collect_livekit_provider_inventory" in text
    assert "turn_allocation_inventory_available: bool = False" in text
    assert "turn_allocation_drain_verified: bool = False" in text
    assert "coturn_allocation_inventory_unavailable" in text
    assert "provider_drain_verified: bool = False" in text
    assert "full_host_closure: bool = False" in text
    assert "migration_0064_rollout_allowed: bool = False" in text
    assert "requires_independent_rollout_window: bool = True" in text


def test_turn_boundary_is_read_only_and_blocks_rollout_without_cleanup_or_settlement():
    calls = _calls(SERVICE)
    forbidden = (
        ".commit", ".rollback", ".add", ".delete", ".unlink", ".remove",
        ".replace", ".rename", "settle_", "delete_room", "remove_participant",
        "stop_egress", "start_room_recording",
    )
    assert not any(call.endswith(forbidden) or call.startswith(forbidden) for call in calls)
    text = SERVICE.read_text()
    assert "rollout_blocker_reasons" in text
    assert "livekit_provider_inventory_unverified" in text
    assert "livekit_aios_rooms_still_present" in text
    assert "livekit_participants_still_present" in text
    assert "coturn_allocation_inventory_unavailable" in text


def test_plan_advances_to_turn_boundary_without_provider_or_full_host_claim():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B4"
    assert item["source_part"] == "FR-06C5D9B3D"
    assert item["prerequisite_source_part"] == "FR-06C5D9B3C"
    assert item["livekit_provider_inventory_consumed"] is True
    assert item["coturn_allocation_inventory_available"] is False
    assert item["turn_allocation_drain_verified"] is False
    assert item["migration_0064_rollout_allowed"] is False
    assert item["requires_independent_rollout_window"] is True
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()
    assert PHASE36_RECEIPT.is_file()
