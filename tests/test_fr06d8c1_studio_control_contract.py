"""Source boundaries complement the isolated Studio control PostgreSQL tests."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web-dashboard/backend/app"
API = APP / "api/v1/endpoints/studio.py"
HELPER = APP / "services/studio_control_evidence.py"


def _function(path, name):
    tree = ast.parse(path.read_text())
    nodes = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    assert len(nodes) == 1
    return nodes[0]


def _calls(node):
    return [ast.unparse(item.func) for item in ast.walk(node) if isinstance(item, ast.Call)]


@pytest.mark.parametrize("name", ["cancel_job", "retry_job"])
def test_retained_evidence_is_checked_after_tenant_lock_before_mutation(name):
    source = ast.unparse(_function(API, name))
    assert source.index("await _job_or_404") < source.index("await _retained_studio_control_evidence")
    assert "lock=True" in source
    mutation = "job.cancelled_at =" if name == "cancel_job" else "job.status ="
    assert source.index("await _retained_studio_control_evidence") < source.index(mutation)
    assert source.index(mutation) < source.index("await session.commit()")


def test_locked_job_refreshes_cached_state_without_autoflush():
    source = ast.unparse(_function(API, "_job_or_404"))
    assert "StudioJob.organization_id == actor.organization_id" in source
    assert "populate_existing=True" in source and "session.no_autoflush" in source
    assert source.index("with_for_update") < source.index("await session.scalar")


def test_history_checks_all_three_ledgers_without_generation_or_state_filter():
    node = _function(HELPER, "has_retained_studio_evidence")
    source = ast.unparse(node)
    for model in ("StudioExecution", "StudioPublication", "StudioSettlement"):
        assert model + ".job_id == job_id" in source
    assert "admitted_generation" not in source and ".state" not in source
    assert _calls(node).count("session.scalar") == 1
    assert "session.no_autoflush" in source and "session.in_transaction()" in source
    assert "type(found) is not bool" in source


def test_history_reader_does_not_commit_or_modify_ledger_or_files():
    calls = _calls(_function(HELPER, "has_retained_studio_evidence"))
    forbidden = (".commit", ".rollback", ".flush", ".delete", ".add", ".unlink", ".write_bytes", ".run_in_executor")
    assert not any(call.endswith(forbidden) for call in calls)


def test_evidence_failure_is_a_sanitized_503_not_an_empty_history():
    node = _function(API, "_retained_studio_control_evidence")
    source = ast.unparse(node)
    assert "StudioControlEvidenceUnavailable" in source
    assert "status_code=503" in source
    assert "Studio control evidence is currently unavailable." in source
    assert "return False" not in source and "str(exc)" not in source


def test_cancellation_remains_available_during_admission_closure():
    source = ast.unparse(_function(API, "cancel_job"))
    assert "_require_studio_request_admission" not in source
    assert "retry_has_no_execution_provenance(job) and (not retained_history)" in source
    assert "cancel_requested" in source and "cleanup_verified" in source


def test_retry_keeps_maintenance_admission_before_row_lock():
    source = ast.unparse(_function(API, "retry_job"))
    assert source.index("await _require_studio_request_admission") < source.index("await _job_or_404")
    assert "evidence-based reconciliation" in source


def test_control_contract_preserves_source_only_boundary():
    import json
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    contract = fr06["host_state_cutover_admission"]["studio_control_evidence_source"]
    assert contract["retained_ledgers"] == ["studio_executions", "studio_publications", "studio_settlements"]
    assert contract["fresh_tenant_job_lock"] is True
    assert contract["additional_migration_required"] is False
    for key in ("production_deployment_verified", "full_host_closure", "post_crash_cleanup_implemented", "cancellation_settlement_implemented"):
        assert contract[key] is False
