"""Source contract for FR-06C5D9B2B1 LiveKit room ownership wiring."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "web-dashboard/backend/app/api/v1/endpoints/realtime_media.py"
SERVICE = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_resources.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B2B1-realtime-room-provider-ownership.md"


def _function(name: str) -> str:
    tree = ast.parse(ROUTES.read_text())
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == name]
    assert len(matches) == 1
    return ast.unparse(matches[0])


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_room_provider_ownership_source"]


def test_create_room_orders_durable_intent_lock_capability_provider_and_local_open():
    source = _function("create_room")
    reserve = source.index("reserve_provider_resource")
    commit = source.index("await session.commit()", reserve)
    lock = source.index("_room_or_404(session, actor, room.id, lock=True)", commit)
    begin = source.index("begin_provider_io", lock)
    provider = source.index("livekit_runtime.provision_room", begin)
    observe = source.index("observe_provider_active", provider)
    local_open = source.index("room.status = 'open'", observe)
    assert reserve < commit < lock < begin < provider < observe < local_open
    assert "delete_room" not in source
    assert "provider_created" not in source


def test_create_room_retains_provider_ambiguity_without_automatic_cleanup():
    source = _function("create_room")
    assert "mark_provider_unresolved" in source
    assert "room_create_" in source
    assert "await session.rollback()" in source
    assert "settle_not_started" in source
    assert "HostMaintenanceClosed" in source
    assert "HostMaintenanceUnavailable" in source


def test_close_room_never_settles_submitted_inflight_create():
    source = _function("close_room")
    submitted = source.index("owner_state == 'submitted'")
    delete = source.index("livekit_runtime.delete_room", submitted)
    settle = source.index("settle_room_absent", delete)
    assert submitted < delete < settle
    assert "Realtime room provider start is not yet reconciled." in source
    assert "mark_provider_unresolved" in source
    assert "settle_not_started" in source


def test_locked_room_reads_refresh_after_transaction_boundaries():
    source = ROUTES.read_text()
    helper = source[source.index("async def _room_or_404"):source.index("async def _recording_or_404")]
    assert ".with_for_update().execution_options(populate_existing=True)" in helper


def test_room_absence_settlement_requires_active_or_unresolved_owner():
    source = SERVICE.read_text()
    function = source[source.index("async def settle_room_absent"):]
    assert 'row.state not in {"active", "unresolved"}' in function
    assert 'row.provider_ref_sha256 not in (None, provider_ref_sha256)' in function
    assert 'row.state = "settled"' in function
    assert 'row.unresolved_reason = None' in function


def test_plan_scopes_room_wiring_without_claiming_other_realtime_resources():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B3C"
    assert item["room_create_wired"] is True
    assert item["room_close_wired"] is True
    assert item["join_session_wired"] is False
    assert item["egress_wired"] is False
    assert item["recording_file_wired"] is False
    assert item["room_row_lock_held_across_provider_start"] is True
    assert item["submitted_room_close_settlement_permitted"] is False
    assert item["automatic_provider_cleanup_after_ambiguous_create"] is False
    assert item["production_database_migrated"] is False
    assert item["production_deployment_verified"] is False
    assert item["session_drain_verified"] is False
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()
