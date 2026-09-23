"""Source inventory contract for FR-06C5D9B1 Realtime runtime ownership."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "web-dashboard/backend/app/db/models.py"
LIVEKIT = ROOT / "web-dashboard/backend/app/realtime/livekit_runtime.py"
MEDIA = ROOT / "web-dashboard/backend/app/services/realtime_media_runtime.py"
ROUTES = ROOT / "web-dashboard/backend/app/api/v1/endpoints/realtime_media.py"
PLAN = ROOT / "docs/project/PLAN.json"
RECEIPT = ROOT / "docs/project/receipts/FR-06C5D9B1-realtime-runtime-ownership-inventory.md"


def item():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    return root, root["realtime_runtime_ownership_inventory_source"]


def test_current_part_is_inventory_only_after_d9a():
    root, inv = item()
    assert root["source_part"] == "FR-06C5D9B3D"
    assert inv["source_part"] == "FR-06C5D9B1"
    assert inv["prerequisite_source_part"] == "FR-06C5D9A"
    assert inv["inventory_only"] is True
    assert inv["production_execution_performed"] is False
    assert inv["production_database_migrated"] is False
    assert inv["production_deployment_verified"] is False
    assert inv["full_host_closure"] is False


def test_durable_realtime_models_and_identifiers_exist():
    text = MODELS.read_text()
    for name in ("class RealtimeRoom", "class RealtimeParticipant", "class RealtimeAdmissionGrant", "class RealtimeRecording", "class RealtimeRecordingConsent"):
        assert name in text
    for field in ("provider_room_id_sha256", "presence_lease_expires_at", "provider_token_jti_sha256", "expires_at", "provider_egress_id", "output_relpath", "output_checksum_sha256"):
        assert field in text


def test_external_provider_resource_edges_are_real_and_separate():
    livekit = LIVEKIT.read_text()
    for method in ("delete_room", "remove_participant", "participant_session", "start_room_recording", "list_egress", "stop_egress", "recording_path"):
        assert f"def {method}(" in livekit or f"async def {method}(" in livekit
    routes = ROUTES.read_text()
    assert "provider_token_jti_sha256 = provider_session.token_jti_sha256" in routes
    assert "recording.provider_egress_id = state.egress_id" in routes
    assert "await livekit_runtime.delete_room" in routes
    assert "await livekit_runtime.remove_participant" in routes
    assert "await livekit_runtime.stop_egress" in routes
    assert "await livekit_runtime.list_egress" in routes


def test_inventory_records_missing_maintenance_ownership_without_claiming_drain():
    _, inv = item()
    assert inv["maintenance_operation_generation_binding_present"] is False
    assert inv["durable_provider_call_ownership_present"] is False
    assert inv["provider_token_expiry_bound_to_maintenance_operation"] is False
    assert inv["turn_credential_expiry_persisted"] is False
    assert inv["provider_room_existence_reconciled_durably"] is False
    assert inv["egress_completion_reconciled_durably_for_host_drain"] is False
    assert inv["recording_file_finalization_owned_by_maintenance_cycle"] is False
    assert inv["session_drain_verified"] is False
    assert inv["provider_drain_verified"] is False
    assert inv["generic_host_cycle_supports_realtime_as_is"] is False
    assert inv["generic_host_cycle_consumer_constraint_excludes_realtime"] is True
    assert inv["generic_host_cycle_has_realtime_resource_type_discriminator"] is False
    model_text = MODELS.read_text()
    host_cycle = model_text[model_text.index("class HostMaintenanceWorkCycle"):model_text.index("class OwnerCommandRecord") ]
    assert "realtime_media_requests" not in host_cycle


def test_existing_durable_signals_are_not_overclaimed():
    _, inv = item()
    assert inv["room_provider_id_hash_persisted"] is True
    assert inv["grant_expiry_persisted"] is True
    assert inv["provider_token_jti_hash_persisted"] is True
    assert inv["egress_id_persisted"] is True
    assert inv["recording_output_path_persisted"] is True
    assert inv["participant_presence_lease_persisted"] is True
    assert RECEIPT.is_file()
    text = RECEIPT.read_text()
    assert "operation_id" in text and "generation" in text
    assert "full_host_closure` remains false" in text


def test_recording_finalization_is_real_filesystem_work_not_drain_proof():
    text = MEDIA.read_text()
    assert "livekit_runtime.recording_path" in text
    assert "shutil.copyfileobj" in text
    assert "os.fsync" in text
    assert "source.unlink" in text
    _, inv = item()
    assert inv["recording_file_finalization_owned_by_maintenance_cycle"] is False
