"""Source contract for FR-06C5D9B2B4 recording-file ownership."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "web-dashboard/backend/app/api/v1/endpoints/realtime_media.py"
MEDIA = ROOT / "web-dashboard/backend/app/services/realtime_media_runtime.py"
LEDGER = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_resources.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B2B4-realtime-recording-file-ownership.md"


def _block(text: str, start: str, end: str | None) -> str:
    begin = text.index(start)
    finish = len(text) if end is None else text.index(end, begin)
    return text[begin:finish]


def _item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_recording_file_ownership_source"]


def test_start_commits_egress_and_recording_file_intents_before_one_bundle_begin():
    text = ROUTES.read_text()
    start = _block(text, "async def _start_recording_provider(", "async def _refresh_recording_provider(")
    shared_incarnation = start.index("owner_incarnation = str(uuid4())")
    egress_kind = start.index('resource_kind="egress"', shared_incarnation)
    file_kind = start.index('resource_kind="recording_file"', egress_kind)
    commit = start.index("await session.commit()", file_kind)
    begin = start.index("begin_provider_io_bundle((owner, file_owner))", commit)
    provider = start.index("livekit_runtime.start_room_recording", begin)
    file_active = start.index("file_owner, provider_ref_sha256=file_ref_sha256", provider)
    egress_settle = start.index("settle_egress_terminal", file_active)
    business = start.index("recording.provider_egress_id = state.egress_id", egress_settle)
    assert shared_incarnation < egress_kind < file_kind < commit < begin < provider
    assert provider < file_active < egress_settle < business
    assert "recording_file_start_" in start
    assert "settle_not_started_in_session(session, file_owner)" in start


def test_recording_file_identity_is_durable_and_not_raw_path_material():
    text = ROUTES.read_text()
    helper = _block(text, "def _recording_file_ref_sha256(", "async def _settle_recording_file_after_commit(")
    assert "recording.id" in helper
    assert "recording.output_relpath" in helper
    assert "egress_id" in helper
    assert "hashlib.sha256" in helper
    assert "return recording.output_relpath" not in helper


def test_completed_file_settles_only_after_business_commit_and_source_absence():
    text = ROUTES.read_text()
    helper = _block(
        text,
        "async def _settle_recording_file_after_commit(",
        "async def _start_recording_provider(",
    )
    assert 'provider_status == "EGRESS_COMPLETE"' in helper
    assert "recording.studio_asset_id is None" in helper
    assert "recording.output_checksum_sha256 is None" in helper
    lstat = helper.index("os.lstat(source)")
    settle = helper.index("settle_recording_file_absent", lstat)
    assert lstat < settle
    assert "recording_file_present_after_terminal" in helper

    refresh = _block(text, "async def _refresh_recording_provider(", '@router.get("/media/readiness")')
    update = refresh.index("update_from_provider_state")
    commit = refresh.index("await session.commit()", update)
    file_settle = refresh.index("_settle_recording_file_after_commit", commit)
    assert update < commit < file_settle

    stop = _block(text, "async def stop_recording(", None)
    update = stop.index("update_from_provider_state")
    commit = stop.index("await session.commit()", update)
    file_settle = stop.index("_settle_recording_file_after_commit", commit)
    assert update < commit < file_settle

    media = MEDIA.read_text()
    finalizer = _block(media, "async def finalize_completed_recording(", "async def update_from_provider_state(")
    assert "source.unlink(missing_ok=True)" in finalizer


def test_refresh_and_stop_require_both_egress_and_file_owners():
    text = ROUTES.read_text()
    refresh = _block(text, "async def _refresh_recording_provider(", '@router.get("/media/readiness")')
    assert 'resource_kind="egress"' in refresh
    assert 'resource_kind="recording_file"' in refresh
    assert "if owner is None or file_owner is None" in refresh
    assert "file_owner, provider_ref_sha256=file_ref_sha256" in refresh
    assert "recording_file_list_" in refresh
    assert "recording_file_egress_identity_mismatch" in refresh

    stop = _block(text, "async def stop_recording(", None)
    assert 'resource_kind="egress"' in stop
    assert 'resource_kind="recording_file"' in stop
    assert "if owner is None or file_owner is None" in stop
    assert "file_owner, provider_ref_sha256=file_ref_sha256" in stop
    assert "recording_file_stop_" in stop
    assert "recording_file_egress_identity_mismatch" in stop


def test_ledger_has_atomic_bundle_begin_and_narrow_file_settlement():
    text = LEDGER.read_text()
    bundle = _block(text, "async def begin_provider_io_bundle(", "async def observe_provider_active(")
    assert "authority = await require_realtime_admission(session)" in bundle
    assert "rows = [await _locked(session, owner) for owner in ordered]" in bundle
    assert 'row.state = "submitted"' in bundle
    assert "provider_started_at = stamp" in bundle

    settle = _block(text, "async def settle_recording_file_absent(", None)
    assert 'owner.resource_kind != "recording_file"' in settle
    assert "provider_status not in _EGRESS_TERMINAL_STATUSES" in settle
    assert 'row.state not in {"active", "unresolved"}' in settle
    assert "row.provider_ref_sha256 != provider_ref_sha256" in settle
    assert 'row.state = "settled"' in settle


def test_plan_advances_to_recording_file_source_without_claiming_production_drain():
    root, item = _item()
    assert root["source_part"] == "FR-06C5D9B3B"
    assert item["source_part"] == "FR-06C5D9B2B4"
    assert item["prerequisite_source_part"] == "FR-06C5D9B2B3"
    assert item["egress_wired"] is True
    assert item["recording_file_wired"] is True
    assert item["egress_and_file_intents_commit_together"] is True
    assert item["provider_start_consumes_bundle_atomically"] is True
    assert item["file_owner_survives_egress_terminal_until_business_commit"] is True
    assert item["file_settlement_requires_explicit_source_absence"] is True
    assert item["automatic_file_cleanup_after_ambiguity"] is False
    assert item["production_database_migrated"] is False
    assert item["production_deployment_verified"] is False
    assert item["recording_file_drain_verified"] is False
    assert item["provider_drain_verified"] is False
    assert item["full_host_closure"] is False
    assert RECEIPT.is_file()
