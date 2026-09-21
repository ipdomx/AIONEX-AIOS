"""Source contract for FR-06C5D9B2B2 participant-session ownership."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "web-dashboard/backend/app/api/v1/endpoints/realtime_media.py"
LIVEKIT = ROOT / "web-dashboard/backend/app/realtime/livekit_runtime.py"
LEDGER = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_resources.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B2B2-realtime-participant-session-ownership.md"
PHASE36_RECEIPT = ROOT / "docs/phase-36/receipts/36H-2026-09-21-realtime-participant-session-ownership.md"


def _function(source: str, name: str, next_marker: str) -> str:
    start = source.index(f"async def {name}(")
    end = source.index(next_marker, start)
    return source[start:end]


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_participant_session_ownership_source"]


def test_join_orders_grant_intent_commit_relock_begin_mint_observe_consume_return():
    source = ROUTES.read_text()
    join = _function(source, "join_room", '@router.post("/media/rooms/{room_id}/leave")')
    issue = join.index("admission.issue_grant")
    reserve = join.index("reserve_provider_resource", issue)
    grant_identity = join.index("local_resource_id=grant_id", reserve)
    first_commit = join.index("await session.commit()", grant_identity)
    relock = join.index("_room_or_404(session, actor, room.id, lock=True)", first_commit)
    begin = join.index("begin_provider_io", relock)
    mint = join.index("livekit_runtime.participant_session", begin)
    observe = join.index("observe_provider_active", mint)
    consume = join.index("admission.consume_grant", observe)
    final_commit = join.index("await session.commit()", consume)
    response = join.index('"session": provider_session.response_payload()', final_commit)
    assert issue < reserve < grant_identity < first_commit < relock < begin < mint < observe < consume < final_commit < response
    assert 'resource_kind="participant_session"' in join
    assert "settle_not_started_in_session" in join
    assert "HostMaintenanceClosed" in join
    assert "HostMaintenanceUnavailable" in join


def test_join_persists_whole_jwt_turn_bundle_before_response():
    join = _function(ROUTES.read_text(), "join_room", '@router.post("/media/rooms/{room_id}/leave")')
    assert "provider_session.ownership_ref_sha256" in join
    assert "provider_session.drain_expires_at" in join
    assert "provider_session.token_jti_sha256" in join
    assert "participant_session_max_ttl" in join
    assert "mark_provider_unresolved" in join
    assert "expires_at=conservative_expiry" in join


def test_livekit_bundle_has_internal_whole_credential_identity_and_deadline():
    text = LIVEKIT.read_text()
    assert "ownership_ref_sha256: str" in text
    assert "drain_expires_at: datetime" in text
    assert "participant_session_max_ttl" in text
    assert "max(expires, turn_expiry)" in text
    assert 'f"{token_jti_sha256}:{turn_name_sha256}"' in text
    response = text[text.index("def response_payload"):text.index("class ProviderEgressState")]
    assert "ownership_ref_sha256" not in response
    assert "drain_expires_at" not in response


def test_leave_does_not_claim_credential_revocation_or_session_settlement():
    source = ROUTES.read_text()
    leave = _function(source, "leave_room", '@router.post("/media/rooms/{room_id}/close")')
    assert "remove_participant" in leave
    assert "settle_participant_session_expired" not in leave
    assert "settle_not_started" not in leave
    assert "participant_session" not in leave


def test_participant_session_settlement_uses_database_clock_after_bundle_expiry():
    text = LEDGER.read_text()
    start = text.index("async def settle_participant_session_expired")
    function = text[start:]
    assert 'owner.resource_kind != "participant_session"' in function
    assert 'row.state not in {"active", "unresolved"}' in function
    assert "row.expires_at is None" in function
    assert "stamp = await _now(session)" in function
    assert "if stamp < row.expires_at" in function
    assert 'row.state = "settled"' in function
    assert "func.clock_timestamp()" in text


def test_plan_scopes_b2b2_without_claiming_egress_file_or_drain():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B2B3"
    assert item["source_part"] == "FR-06C5D9B2B2"
    assert item["prerequisite_source_part"] == "FR-06C5D9B2B1"
    assert item["ownership_local_resource"] == "realtime_admission_grant.id"
    assert item["join_session_wired"] is True
    assert item["egress_wired"] is False
    assert item["recording_file_wired"] is False
    assert item["grant_and_provider_intent_commit_before_credential_mint"] is True
    assert item["provider_start_rechecks_same_generation"] is True
    assert item["jwt_expiry_included_in_drain_deadline"] is True
    assert item["turn_expiry_included_in_drain_deadline"] is True
    assert item["leave_does_not_settle_unexpired_session"] is True
    assert item["db_clock_expiry_required_for_settlement"] is True
    assert item["credential_bundle_expiry_is_not_connected_presence_drain"] is True
    assert item["livekit_connected_participant_drain_verified"] is False
    assert item["turn_allocation_drain_verified"] is False
    assert item["production_database_migrated"] is False
    assert item["production_deployment_verified"] is False
    assert item["session_drain_verified"] is False
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()
    assert PHASE36_RECEIPT.is_file()
    phase36 = PHASE36_RECEIPT.read_text()
    assert "does not certify Realtime session drain or full-host closure" in phase36
    assert "does not deploy migration `20260920_0064` to Production" in phase36
