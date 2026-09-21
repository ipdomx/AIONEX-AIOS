"""Source contract for FR-06C5D9B2B3 LiveKit Egress ownership."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "web-dashboard/backend/app/api/v1/endpoints/realtime_media.py"
LEDGER = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_resources.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B2B3-realtime-egress-ownership.md"


def _block(text: str, start: str, end: str | None) -> str:
    begin = text.index(start)
    finish = len(text) if end is None else text.index(end, begin)
    return text[begin:finish]


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_egress_ownership_source"]


def test_start_orders_intent_commit_begin_provider_observe_before_business_identifier():
    text = ROUTES.read_text()
    start = _block(text, "async def _start_recording_provider(", "async def _refresh_recording_provider(")
    reserve = start.index("reserve_provider_resource")
    kind = start.index('resource_kind="egress"', reserve)
    commit = start.index("await session.commit()", kind)
    relock = start.index("_recording_or_404(session, actor, recording.id, lock=True)", commit)
    begin = start.index("begin_provider_io", relock)
    provider = start.index("livekit_runtime.start_room_recording", begin)
    observe = start.index("observe_provider_active", provider)
    business = start.index("recording.provider_egress_id = state.egress_id", observe)
    assert reserve < kind < commit < relock < begin < provider < observe < business
    assert "find_unfinished_provider_ownership" in start
    assert "mark_provider_unresolved" in start
    assert "provider_start_uncertain" in start
    assert "settle_egress_terminal" in start


def test_refresh_does_not_restart_unresolved_start_and_requires_identity_match():
    text = ROUTES.read_text()
    refresh = _block(text, "async def _refresh_recording_provider(", '@router.get("/media/readiness")')
    assert "find_unfinished_provider_ownership" in refresh
    assert "Realtime Egress start ownership requires reconciliation." in refresh
    assert "verify_provider_reference" in refresh
    assert "livekit_runtime.list_egress" in refresh
    assert "egress_list_identity_mismatch" in refresh
    assert "settle_egress_terminal" in refresh


def test_stop_acknowledgement_is_not_terminal_settlement():
    text = ROUTES.read_text()
    stop = _block(text, 'async def stop_recording(', None)
    stop_call = stop.index("livekit_runtime.stop_egress")
    terminal_gate = stop.index("if owner is not None and state.terminal", stop_call)
    settle = stop.index("settle_egress_terminal", terminal_gate)
    update = stop.index("update_from_provider_state", settle)
    assert stop_call < terminal_gate < settle < update
    assert "verify_provider_reference" in stop
    assert "egress_stop_identity_mismatch" in stop
    assert "mark_provider_unresolved" in stop


def test_ledger_terminal_settlement_is_explicit_and_narrow():
    text = LEDGER.read_text()
    assert '_EGRESS_TERMINAL_STATUSES = frozenset({' in text
    for status in ("EGRESS_COMPLETE", "EGRESS_FAILED", "EGRESS_ABORTED"):
        assert f'"{status}"' in text
    function = _block(text, "async def settle_egress_terminal(", None)
    assert "provider_status not in _EGRESS_TERMINAL_STATUSES" in function
    assert 'row.state not in {"active", "unresolved"}' in function
    assert "row.provider_ref_sha256 != provider_ref_sha256" in function
    assert 'row.state = "settled"' in function
    assert "EGRESS_ENDING" not in function


def test_plan_keeps_file_and_full_drain_open():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B2B4"
    assert item["source_part"] == "FR-06C5D9B2B3"
    assert item["prerequisite_source_part"] == "FR-06C5D9B2B2"
    assert item["egress_wired"] is True
    assert item["recording_file_wired"] is False
    assert item["recording_and_egress_intent_commit_before_start"] is True
    assert item["provider_start_rechecks_same_generation"] is True
    assert item["start_ambiguity_retained_without_automatic_retry"] is True
    assert item["stop_acknowledgement_is_not_terminal_proof"] is True
    assert item["terminal_settlement_requires_explicit_provider_observation"] is True
    assert item["production_database_migrated"] is False
    assert item["production_deployment_verified"] is False
    assert item["recording_file_drain_verified"] is False
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()
