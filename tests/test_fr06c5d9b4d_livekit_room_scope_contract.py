"""Permanent contract for the real-provider room-admin regression correction."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_participant_admin_grants_bind_only_the_requested_room():
    tree = ast.parse((ROOT / "web-dashboard/backend/app/realtime/livekit_runtime.py").read_text())
    runtime = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LiveKitRuntime")
    for name, variable in (("remove_participant", "provider_room_name"), ("list_room_participant_inventory", "room_name")):
        method = next(n for n in runtime.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
        call = next(n for n in ast.walk(method) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_twirp")
        grant = next(k.value for k in call.keywords if k.arg == "video_grant")
        assert isinstance(grant, ast.Dict)
        values = {ast.literal_eval(k): v for k, v in zip(grant.keys, grant.values)}
        assert set(values) == {"room", "roomAdmin"}
        assert ast.literal_eval(values["roomAdmin"]) is True
        assert isinstance(values["room"], ast.Name) and values["room"].id == variable


def test_room_admin_acceptance_preserves_isolated_and_production_boundaries():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    batch = next(b for b in plan["batches"] if b["id"] == "FR-06")
    item = batch["host_state_cutover_admission"]["realtime_room_scoped_admin_correction_source"]
    assert item["source_part"] == "FR-06C5D9B4D"
    assert item["real_pinned_livekit_isolated_control_plane_executed"] is True
    assert item["real_synthetic_signaling_participant_observed_and_removed"] is True
    for field in ("production_database_migrated", "production_deployment_verified", "production_execution_performed", "audio_video_tracks_tested", "turn_allocation_drain_verified", "provider_drain_verified", "full_host_closure"):
        assert item[field] is False
    assert all((ROOT / path).is_file() for path in item["evidence"])
    assert (ROOT / "web-dashboard/backend/tests/test_fr06c5d9b4d_livekit_room_scope.py").is_file()
