"""Source boundaries for proven pre-start cancellation, not payload cleanup."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web-dashboard/backend/app"
SERVICE = APP / "services/studio_prestart_cancellation.py"
REGISTRY = APP / "services/studio_resource_registry.py"


def _function(path, name):
    tree = ast.parse(path.read_text())
    return next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def _calls(node):
    return [ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)]


def test_exact_active_claim_is_required_not_absence_of_files_or_age():
    source = ast.unparse(_function(SERVICE, "_untouched_claim"))
    for marker in ("row.state != 'active'", "row.phase != 'claimed'", "row.resources != {}", "row.started_at != row.updated_at"):
        assert marker in source
    assert "lease_expires" not in SERVICE.read_text()
    assert not any(call.endswith((".exists", ".is_file", ".stat", ".unlink", ".rmdir")) for call in _calls(_function(SERVICE, "_untouched_claim")))


def test_claim_nonce_generation_and_business_provenance_are_rechecked():
    source = ast.unparse(_function(SERVICE, "_eligible"))
    for marker in ("job.lease_token == owner.nonce", "job.attempts == 1", "guard['phase'] == 'claimed'", "guard['worker_incarnation'] == owner.worker_incarnation", "guard['admitted_generation'] == owner.admitted_generation"):
        assert marker in source
    assert "job.provider is None" in source and "job.started_at" in source


def test_receipt_and_job_mutations_are_owned_by_the_callers_transaction():
    node = _function(SERVICE, "cancel_claimed_before_start")
    calls = _calls(node)
    assert "session.add" in calls
    assert not any(call.endswith((".commit", ".flush", ".rollback", ".delete", ".unlink", ".write_bytes")) for call in calls)
    source = ast.unparse(node)
    assert source.index("select(StudioJob)") < source.index("select(StudioExecution)")
    assert "session.no_autoflush" in source and "populate_existing=True" in source
    assert source.index("validate_receipt(receipt, row)") < source.index("locked_job.status = 'cancelled'")


def test_receipt_does_not_claim_started_work_stopped_or_files_were_deleted():
    source = SERVICE.read_text()
    assert '"payload_resources_started": False' in source
    assert '"filesystem_cleanup_claimed": False' in source
    assert '"full_host_closure": False' in source
    assert not any(call.endswith((".unlink", ".remove", ".rmtree", ".truncate", ".run_in_executor", ".to_thread")) for call in _calls(ast.parse(source)))


@pytest.mark.parametrize("name,path", [
    ("register_claim", REGISTRY), ("begin_registered", REGISTRY),
    ("_claim", APP / "services/studio_worker.py"),
    ("has_retained_studio_evidence", APP / "services/studio_control_evidence.py"),
])
def test_all_replay_entrypoints_consider_independent_prestart_receipt(name, path):
    assert "StudioPrestartCancellation" in ast.unparse(_function(path, name))


def test_snapshot_keeps_invalid_and_orphan_proof_as_a_blocker():
    source = ast.unparse(_function(REGISTRY, "execution_snapshot"))
    assert "snapshot_prestart_cancellations" in source
    assert "invalid_prestart_cancellation_count" in source
    assert "len(cancelled)" in source and "invalid_cancellations" in source
    assert "'coverage_unverified': True" in source and "'full_host_closure': False" in source


def test_migration_does_not_backfill_or_discard_cancellation_provenance():
    path = ROOT / "web-dashboard/backend/alembic/versions/20260919_0058_studio_prestart_cancellation.py"
    source = path.read_text()
    assert 'down_revision = "20260919_0057"' in source
    assert "from app." not in source and "frozen schema" in source
    assert any(isinstance(node, ast.Raise) for node in ast.walk(_function(path, "downgrade")))
    assert not any(call.endswith((".delete", ".update")) for call in _calls(ast.parse(source)))


def test_roadmap_distinguishes_prestart_source_from_poststart_cleanup():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    batch = next(item for item in plan["batches"] if item["id"] == "FR-06")
    entry = batch["host_state_cutover_admission"]["studio_prestart_cancellation_source"]
    assert entry["migration"] == "20260919_0058"
    assert entry["claimed_but_never_started_only"] is True
    for key in ("post_start_cancellation_settlement", "post_crash_cleanup_implemented", "production_deployment_verified", "full_host_closure"):
        assert entry[key] is False
