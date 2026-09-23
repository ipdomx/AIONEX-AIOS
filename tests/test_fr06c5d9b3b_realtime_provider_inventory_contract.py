"""Source contract for FR-06C5D9B3B LiveKit provider inventory drain gate."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVEKIT = ROOT / "web-dashboard/backend/app/realtime/livekit_runtime.py"
SERVICE = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_provider_inventory.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B3B-realtime-provider-inventory.md"


def _calls(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_provider_inventory_source"]


def test_livekit_inventory_returns_hashes_not_raw_room_or_participant_names():
    text = LIVEKIT.read_text()
    assert "class ProviderRoomInventory" in text
    assert "async def list_aios_room_name_hashes" in text
    assert "method=\"ListRooms\"" in text
    assert "name.startswith(\"aios-rt-\")" in text
    assert "hashlib.sha256(name.encode" in text
    assert "async def list_room_participant_inventory" in text
    assert "method=\"ListParticipants\"" in text
    assert "hashlib.sha256(identity.encode" in text
    assert "return tuple(rooms" not in text
    assert "participant_identity_sha256" in text


def test_provider_inventory_service_requires_durable_clear_snapshot_before_provider_io():
    text = SERVICE.read_text()
    before = text.index("drain = await measure_realtime_drain")
    gate = text.index("if not drain.is_clear", before)
    provider = text.index("runtime.list_aios_room_inventory", gate)
    assert before < gate < provider
    assert "durable Realtime blockers must be reconciled" in text
    assert "turn_allocation_drain_verified=False" in text
    assert "provider_drain_verified=False" in text
    calls = _calls(SERVICE)
    forbidden = (".commit", ".rollback", ".add", ".delete", ".unlink", ".remove", ".replace", ".rename")
    assert not any(call.endswith(forbidden) for call in calls)


def test_plan_advances_to_provider_inventory_without_claiming_full_drain():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B3C"
    assert item["source_part"] == "FR-06C5D9B3B"
    assert item["prerequisite_source_part"] == "FR-06C5D9B3A"
    assert item["provider_io_source_present"] is True
    assert item["durable_snapshot_clear_required_before_provider_io"] is True
    assert item["raw_provider_room_names_returned"] is False
    assert item["raw_participant_identities_returned"] is False
    assert item["turn_allocation_drain_verified"] is False
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()
