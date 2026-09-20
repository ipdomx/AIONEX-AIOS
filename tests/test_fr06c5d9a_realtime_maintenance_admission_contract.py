"""Source invariants for FR-06C5D9A Realtime maintenance admission."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "web-dashboard/backend/app/services/host_maintenance_admission.py"
GUARD = ROOT / "web-dashboard/backend/app/services/host_maintenance_realtime_admission.py"
ROUTES = ROOT / "web-dashboard/backend/app/api/v1/endpoints/realtime_media.py"
MIGRATION = ROOT / "web-dashboard/backend/alembic/versions/20260920_0063_realtime_media_admission.py"
PLAN = ROOT / "docs/project/PLAN.json"
DB_TEST = ROOT / "web-dashboard/backend/tests/test_database_settings.py"


def _function(path: Path, name: str):
    tree = ast.parse(path.read_text())
    matches = [
        item for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_authority_schema8_extends_schema7_with_realtime_only():
    text = AUTH.read_text()
    assert 'REALTIME_REQUEST_SCHEMA_VERSION = 8' in text
    assert 'REALTIME_REQUEST_COVERAGE_SCOPE = STUDIO_REQUEST_COVERAGE_SCOPE + "+realtime_media_requests"' in text
    assert 'realtime_media_requests' in text
    assert '(REALTIME_REQUEST_SCHEMA_VERSION, REALTIME_REQUEST_COVERAGE_SCOPE)' in text


def test_guard_is_thin_transaction_retaining_wrapper():
    text = GUARD.read_text()
    assert 'CONSUMER = "realtime_media_requests"' in text
    assert 'require_admission_open(session, required_scope=CONSUMER)' in text
    for forbidden in ("commit(", "rollback(", "livekit", "create_room", "start_room_recording"):
        assert forbidden not in text.lower()


def test_new_or_resumed_realtime_work_is_guarded():
    route = ROUTES.read_text()
    for name in ("create_room", "join_room", "request_recording"):
        source = ast.unparse(_function(ROUTES, name))
        assert "await _require_realtime_open(session)" in source
    consent = ast.unparse(_function(ROUTES, "recording_consent"))
    assert "if data.consented" in consent
    assert "await _require_realtime_open(session)" in consent
    provider = ast.unparse(_function(ROUTES, "_start_recording_provider"))
    assert provider.index("await _require_realtime_open(session)") < provider.index("livekit_runtime.start_room_recording")
    refresh = ast.unparse(_function(ROUTES, "_refresh_recording_provider"))
    assert "_start_recording_provider" in refresh


def test_cleanup_control_routes_remain_available_while_closed():
    for name in ("leave_room", "close_room", "stop_recording"):
        source = ast.unparse(_function(ROUTES, name))
        assert "_require_realtime_open" not in source


def test_migration_0063_is_linear_non_destructive_and_preserves_control_state():
    text = MIGRATION.read_text()
    assert 'revision = "20260920_0063"' in text
    assert 'down_revision = "20260920_0062"' in text
    assert 'payload["schema_version"] != 7' in text
    assert 'schema_version=8' in text
    assert 'realtime_media_requests' in text
    for forbidden in (
        "realtime_rooms", "realtime_participants", "realtime_admission_grants",
        "realtime_recordings", "livekit", "http://", "https://",
    ):
        assert forbidden not in text.lower()


def test_plan_records_d9a_live_rollout_without_claiming_session_drain():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    root = fr06["host_state_cutover_admission"]
    item = root["realtime_media_request_admission_source"]
    assert item["source_part"] == "FR-06C5D9A"
    assert root["source_part"] == "FR-06C5D9B2B1"
    assert root["implemented_consumer_scope"].endswith("+realtime_media_requests")
    assert item["authority_schema_version"] == 8
    assert item["migration"] == "20260920_0063"
    assert item["provider_recording_start_rechecks_admission"] is True
    assert item["leave_allowed_during_maintenance"] is True
    assert item["room_close_allowed_during_maintenance"] is True
    assert item["recording_stop_allowed_during_maintenance"] is True
    assert item["production_database_migrated"] is True
    assert item["production_deployment_verified"] is True
    assert item["coverage_verified"] is True
    assert item["production_request_admission_verified"] is True
    assert item["production_open_generation"] == 16
    assert item["production_rollout_merge_commit"] == "7be95f99a18bfc6d0b3e894cf8ae8992962f0383"
    assert item["session_drain_verified"] is False
    assert item["durable_livekit_ownership_verified"] is False
    assert item["livekit_provider_io_performed_by_d9a"] is False
    assert item["full_host_closure"] is False
    assert any(path.endswith("FR-06C5D9A-production-rollout-closeout.md") for path in item["evidence"])
    remaining = root["remaining_before_host_cutover_ar"]
    assert any("realtime/LiveKit" in line and "ملكية دائمة" in line for line in remaining)
    assert any("full-host closure" in line for line in remaining)


def test_backend_keeps_0063_in_the_linear_history_after_0064():
    text = DB_TEST.read_text()
    assert '("20260920_0063", False)' in text
    assert '("20260920_0064", True)' in text
