"""Source-boundary assertions complement real PostgreSQL Studio acceptance."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "web-dashboard/backend/app"
WORKER = APP / "services/studio_worker.py"
API = APP / "api/v1/endpoints/studio.py"
GUARD = APP / "services/studio_execution_guard.py"


def _function(path, name):
    source = path.read_text()
    nodes = [node for node in ast.walk(ast.parse(source)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name]
    assert len(nodes) == 1
    return ast.get_source_segment(source, nodes[0])


@pytest.mark.parametrize("method", ["claim", "claim_by_id"])
def test_public_claim_paths_share_the_same_fenced_implementation(method):
    body = _function(WORKER, method)
    assert "await self._claim(" in body
    assert "session.scalar" not in body


def test_shared_claim_locks_admission_before_selection_and_commit_before_return():
    body = _function(WORKER, "_claim")
    assert body.index("await require_studio_admission") < body.index("select(StudioJob)")
    assert "pristine_conditions()" in body
    assert body.index("await session.commit()") < body.index("return job.id, nonce")
    assert '"cleanup_verified": False' in body


def test_start_is_fenced_before_application_execution():
    body = _function(WORKER, "execute")
    assert body.index("await self._begin_execution") < body.index("await self._execute_claimed")
    start = _function(WORKER, "_begin_execution")
    assert start.index("await require_studio_admission") < start.index("select(StudioJob)")
    assert 'guard["admitted_generation"] != authority.generation' in start
    assert 'guard["worker_incarnation"] != self.incarnation' in start
    assert start.index('set_phase(job, "executing")') < start.index("await session.commit()") < start.index("return True")


def test_worker_contains_no_age_reclaim_or_failure_requeue():
    source = WORKER.read_text()
    assert "stale_before" not in source
    assert "timedelta" not in source
    assert 'job.status = "queued"' not in source
    failed = _function(WORKER, "_failed")
    assert "_mark_unresolved" in failed
    assert "session.commit" not in failed


def test_retry_checks_execution_provenance_before_resetting_attempts():
    body = _function(API, "retry_job")
    assert body.index("await _require_studio_request_admission") < body.index("await _job_or_404")
    assert body.index("retry_has_no_execution_provenance(job)") < body.index("job.attempts = 0")
    assert "evidence-based reconciliation" in body


def test_cancel_intent_does_not_claim_cleanup_or_lose_running_owner():
    body = _function(API, "cancel_job")
    tree = ast.parse(API.read_text())
    node = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "cancel_job")
    branch = next(node for node in ast.walk(node) if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "unstarted")
    alternative = "\n".join(ast.unparse(item) for item in branch.orelse)
    assert "cancel_requested" in alternative and "completed_at = None" in alternative
    assert "lease_token" not in alternative
    assert '"cleanup_verified": False' in body
    assert "require_studio_admission" not in body


def test_guard_is_explicitly_not_a_resource_settlement_record():
    source = GUARD.read_text()
    assert "not a resource registry or a drain receipt" in source
    assert 'guard["cleanup_verified"] is not False' in source
    assert "lease_expires" not in source


def test_success_retains_the_execution_guard_beside_output_metadata():
    body = _function(WORKER, "_execute_claimed")
    assert "**locked.result_metadata" in body
    assert 'set_phase(locked, "returned")' in body
    assert body.index('set_phase(locked, "returned")') < body.rindex("await session.commit()")
