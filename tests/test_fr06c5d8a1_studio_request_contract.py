"""Source boundary contracts complement real PostgreSQL Studio request tests."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
API = BACKEND / "app/api/v1/endpoints/studio.py"
GUARD = BACKEND / "app/services/host_maintenance_studio_admission.py"
MIGRATION = BACKEND / "alembic/versions/20260918_0054_studio_request_admission.py"


def _function(path, name):
    return next(node for node in ast.parse(path.read_text()).body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def _first_await(function):
    for statement in function.body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                call = node.value.func
                return call.id if isinstance(call, ast.Name) else call.attr
    raise AssertionError("expected guarded coroutine")


@pytest.mark.parametrize("name", ["_enqueue_job", "retry_job", "create_revision"])
def test_guard_is_first_await_before_policy_scope_or_business_locks(name):
    assert _first_await(_function(API, name)) == "_require_studio_request_admission"


@pytest.mark.parametrize("name", ["create_job", "generate_artifact_compatibility"])
def test_shared_producer_precedes_legacy_worker_or_response(name):
    assert _first_await(_function(API, name)) == "_enqueue_job"


def test_all_application_studio_job_constructors_have_explicit_queue_or_terminal_scope():
    locations = []
    for path in (BACKEND / "app").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "StudioJob":
                state = next((keyword.value for keyword in node.keywords if keyword.arg == "status"), None)
                assert isinstance(state, ast.Constant), "Unclassified StudioJob writer"
                locations.append((path, node.lineno, state.value))
    producer = _function(API, "_enqueue_job")
    assert len(locations) == 2
    queued = [(path, line) for path, line, state in locations if state == "queued"]
    assert len(queued) == 1
    path, line = queued[0]
    assert path == API and producer.lineno <= line <= producer.end_lineno
    finalizer_path = BACKEND / "app/services/realtime_media_runtime.py"
    finalizer = _function(finalizer_path, "finalize_completed_recording")
    terminal = [(path, line) for path, line, state in locations if state == "completed"]
    assert len(terminal) == 1
    path, line = terminal[0]
    assert path == finalizer_path and finalizer.lineno <= line <= finalizer.end_lineno


def test_realtime_recording_finalization_is_not_blocked_as_a_new_request():
    function = _function(BACKEND / "app/services/realtime_media_runtime.py", "finalize_completed_recording")
    calls = {node.func.id for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not calls & {"require_studio_admission", "_require_studio_request_admission"}


@pytest.mark.parametrize("name", ["list_jobs", "get_job", "cancel_job", "download_asset", "list_revisions"])
def test_existing_read_and_cancellation_paths_are_not_new_request_admission(name):
    function = _function(API, name)
    calls = {node.func.id for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "_require_studio_request_admission" not in calls
    assert "require_studio_admission" not in calls


def test_guard_has_no_commit_seed_worker_or_filesystem_side_effects():
    tree = ast.parse(GUARD.read_text())
    calls = {node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}
    assert not calls & {"commit", "rollback", "flush", "add", "create_task", "to_thread", "execute_scan", "store_artifact", "write_text", "open"}
    assert "require_admission_open" in calls
    assert 'CONSUMER = "studio_job_requests"' in GUARD.read_text()


def test_migration_is_forward_only_and_uses_frozen_validation():
    tree = ast.parse(MIGRATION.read_text())
    constants = {node.targets[0].id: node.value.value for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}
    assert constants["revision"] == "20260918_0054"
    assert constants["down_revision"] == "20260918_0053"
    assert not any(isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.") for node in ast.walk(tree))
    downgrade = _function(MIGRATION, "downgrade")
    assert not any(isinstance(node, ast.Call) for node in ast.walk(downgrade))
    assert "full_host_closure" in MIGRATION.read_text()
    assert "studio_job_requests" in MIGRATION.read_text()
