"""Source contract for FR-06C5D9B3C bounded Realtime provider drain."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVEKIT = ROOT / "web-dashboard/backend/app/realtime/livekit_runtime.py"
SERVICE = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_provider_inventory.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B3C-realtime-provider-drain-boundary.md"
PHASE36_RECEIPT = ROOT / "docs/phase-36/receipts/36H-2026-09-23-realtime-provider-drain-boundary.md"


def _calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_provider_drain_boundary_source"]


def test_livekit_inventory_lists_rooms_then_participants_but_returns_hash_only_snapshots():
    text = LIVEKIT.read_text()
    assert "async def list_aios_room_inventory" in text
    method = text[text.index("async def list_aios_room_inventory"):text.index("async def start_room_recording")]
    list_rooms = method.index('method="ListRooms"')
    participants = method.index("list_room_participant_inventory", list_rooms)
    assert list_rooms < participants
    assert "ProviderRoomInventory" in method
    assert "provider_room_name_sha256" in text
    assert "participant_identity_sha256" in text
    assert "return tuple(" in method
    assert "provider_room_name=name" in method
    assert "Raw LiveKit room names" in method


def test_provider_inventory_binds_durable_snapshot_to_room_and_participant_drain_bounds():
    text = SERVICE.read_text()
    before = text.index("drain = await measure_realtime_drain")
    gate = text.index("if not drain.is_clear", before)
    provider = text.index("runtime.list_aios_room_inventory", gate)
    assert before < gate < provider
    assert "provider_participant_count" in text
    assert "livekit_room_drain_verified=not room_hashes" in text
    assert "connected_presence_provider_drain_verified=participant_count == 0" in text
    assert 'turn_allocation_drain_blocker_reason: str = "coturn_allocation_inventory_unavailable"' in text
    assert "turn_allocation_drain_verified=False" in text
    assert "provider_drain_verified=False" in text
    calls = _calls(SERVICE)
    forbidden = (".commit", ".rollback", ".add", ".delete", ".unlink", ".remove", ".replace", ".rename")
    assert not any(call.endswith(forbidden) for call in calls)


def test_plan_records_bounded_drain_without_turn_or_full_provider_claim():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B3C"
    assert item["source_part"] == "FR-06C5D9B3C"
    assert item["prerequisite_source_part"] == "FR-06C5D9B3B"
    assert item["d9b3a_snapshot_clear_required"] is True
    assert item["livekit_room_inventory_hash_only"] is True
    assert item["livekit_participant_inventory_hash_only"] is True
    assert item["connected_presence_provider_drain_bound"] == "no_livekit_participants_in_aios_rooms"
    assert item["livekit_room_drain_bound"] == "no_aios_livekit_rooms"
    assert item["turn_allocation_drain_verified"] is False
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()
    assert PHASE36_RECEIPT.is_file()
