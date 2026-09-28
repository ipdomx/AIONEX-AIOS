"""Source inventory for supplemental media queue-publication maintenance fences."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web-dashboard/backend/app"
ENTRYPOINTS = (
    ("services/design_image_runtime.py", "arm_design_image_execution", "design_image"),
    ("services/audio_speech_runtime.py", "arm_audio_speech_execution", "audio_speech"),
    ("services/audio_transcript_runtime.py", "arm_audio_transcript_execution", "audio_transcript"),
    ("services/audio_dubbing_runtime.py", "arm_audio_dubbing_execution", "audio_dubbing"),
    ("services/audio_music_runtime.py", "arm_audio_music_execution", "audio_music"),
    ("services/audio_song_runtime.py", "arm_audio_song_execution", "audio_song"),
    ("services/video_runtime.py", "arm_video_execution", "video"),
    ("services/identity_media_runtime.py", "arm_execution", "identity_media"),
    ("services/media_graph_runtime.py", "create_media_graph", "media_graph"),
    ("services/media_graph_runtime.py", "create_partial_media_revision", "media_graph"),
    ("api/v1/endpoints/three_d_jobs.py", "create_three_d_job", "three_d"),
)


def test_queue_publication_entrypoints_begin_with_transactional_fence() -> None:
    assert len(ENTRYPOINTS) == 11
    for path, name, consumer in ENTRYPOINTS:
        tree = ast.parse((APP / path).read_text())
        functions = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == name]
        assert len(functions) == 1
        body = functions[0].body
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        assert isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Await)
        call = body[0].value.value
        assert isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
        assert call.func.id == "require_media_enqueue_admission"
        assert len(call.args) == 1 and isinstance(call.args[0], ast.Name)
        assert call.args[0].id == "session"
        values = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
        assert values == {"consumer": consumer}


def test_enqueue_helper_cannot_commit_reopen_or_call_a_provider() -> None:
    source = (APP / "services/host_maintenance_media_enqueue.py").read_text()
    tree = ast.parse(source)
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "require_studio_admission" in calls
    assert "HTTPException" in calls
    assert not {"session.commit", "session.rollback", "session.add", "session.execute",
                "open_admission", "close_admission", "create_task"}.intersection(calls)
    assert "full_host_closure = True" not in source
    guards = [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]
    assert {ast.unparse(n.type) for n in guards} == {"HostMaintenanceClosed", "HostMaintenanceUnavailable"}


def test_project_receipt_keeps_admission_distinct_from_host_drain() -> None:
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    parent = next(b for b in plan["batches"] if b["id"] == "FR-06")
    part = parent["downstream_media_enqueue_admission_source"]
    assert part["source_part"] == "FR-06C5D10C"
    assert part["guarded_entrypoints"] == len(ENTRYPOINTS)
    assert part["production_deployed"] is False
    assert part["full_host_closure"] is False
    assert part["provider_inventory_verified"] is False
    assert part["database_migration_required"] is False
    for path in part["evidence"]:
        assert (ROOT / path).is_file()
