"""Source boundaries for normal-success settlement; not a runtime drain proof."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
SERVICE = BACKEND / "app/services/studio_success_settlement.py"


def _node(path, name):
    tree = ast.parse(path.read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _calls(node):
    return [ast.unparse(n.func) for n in ast.walk(node) if isinstance(n, ast.Call)]


def test_transactional_validator_neither_commits_nor_launches_filesystem_work():
    calls = _calls(_node(SERVICE, "_record_success"))
    assert "session.add" in calls
    assert not any(call.endswith((".commit", ".flush", ".unlink", ".remove", ".write_bytes", ".to_thread", ".run_in_executor")) for call in calls)
    assert "_owned_evidence" in calls and "_accepted_business" in calls


def test_worker_emits_local_ack_only_after_business_commit_and_session_exit():
    worker = BACKEND / "app/services/studio_worker.py"
    node = _node(worker, "_execute_claimed")
    final = node.body[-1]
    assert isinstance(final, ast.Return)
    assert isinstance(final.value, ast.Call)
    assert ast.unparse(final.value.func) == "studio_success_settlement.acknowledge_business_result"
    previous = node.body[-2]
    assert isinstance(previous, ast.AsyncWith)
    assert isinstance(previous.body[-1], ast.Expr)
    assert ast.unparse(previous.body[-1]) == "await session.commit()"


def test_only_the_worker_issues_business_acknowledgement():
    callers = []
    for path in (BACKEND / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and ast.unparse(node.func).endswith(".acknowledge_business_result"):
                callers.append(path.relative_to(BACKEND).as_posix())
    assert callers == ["app/services/studio_worker.py"]


def test_capability_is_consumed_before_observation_and_single_receipt_commit():
    node = _node(SERVICE, "settle_success")
    source = ast.unparse(node)
    assert "current is not acknowledgement.task" in source
    assert "current.cancelling()" in source
    assert source.index("acknowledgement.consumed = True") < source.index("await registry.observe_execution_end")
    assert source.index("await registry.observe_execution_end") < source.index("await _record_success")
    assert _calls(node).count("session.commit") == 1
    assert not any(isinstance(n, (ast.For, ast.While)) for n in ast.walk(node))


def test_settlement_keeps_archive_and_raw_evidence_instead_of_rewriting_history():
    text = SERVICE.read_text()
    calls = _calls(ast.parse(text))
    assert not any(call.endswith((".delete", ".unlink", ".rmdir", ".remove", ".replace", ".truncate")) for call in calls)
    assert '"accepted_archive_retained": True' in text
    assert '"full_host_closure": False' in text
    assert "proof_sha256" in text and "validate_settlement" in text


def test_migration_is_additive_frozen_and_does_not_backfill_or_erase_receipts():
    path = BACKEND / "alembic/versions/20260919_0057_studio_success_settlement.py"
    text = path.read_text()
    assert 'down_revision = "20260918_0056"' in text
    assert "from app." not in text
    assert "frozen schema" in text
    assert "foreign_keys" in text
    assert not any(call.endswith((".delete", ".update", ".execute_many")) for call in _calls(ast.parse(text)))
    assert any(isinstance(n, ast.Raise) for n in ast.walk(_node(path, "downgrade")))


@pytest.mark.parametrize("name", ["register_claim", "begin_registered", "_claim"])
def test_retained_settlement_prevents_replay_even_when_other_ledgers_disappear(name):
    path = BACKEND / "app/services" / ("studio_worker.py" if name == "_claim" else "studio_resource_registry.py")
    assert "StudioSettlement" in ast.unparse(_node(path, name))


def test_snapshot_separates_settled_receipts_from_legacy_orphan_and_invalid_work():
    node = _node(BACKEND / "app/services/studio_resource_registry.py", "execution_snapshot")
    text = ast.unparse(node)
    for marker in ("snapshot_settlements", "invalid_settlement_count", "settled_execution_count", "unregistered_unverified_job_ids", "orphan_publications", "full_host_closure"):
        assert marker in text
    assert "'is_clear': blockers == 0" in text


def test_settled_end_observations_are_rejected_before_mutating_the_ledger():
    path = BACKEND / "app/services/studio_resource_registry.py"
    source = ast.unparse(_node(path, "observe_execution_end"))
    assert source.index("StudioSettlement.execution_id") < source.index("row.state =")
    assert "Settled Studio execution observations are immutable" in source


def test_plan_records_source_settlement_without_claiming_deployment_or_crash_cleanup():
    import json
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    admission = next(b for b in plan["batches"] if b["id"] == "FR-06")["host_state_cutover_admission"]
    item = admission["studio_success_settlement_source"]
    assert item["normal_success_only"] is True
    assert item["migration"] == "20260919_0057"
    assert item["settled_execution_observations_immutable"] is True
    for key in ("post_crash_cleanup_implemented", "post_crash_reconciliation_implemented", "production_database_migrated", "production_deployment_verified", "full_host_closure", "accepted_archive_deleted", "automatic_uncertain_retry"):
        assert item[key] is False
    for name in ("studio_execution_resources_source", "studio_publication_journal_source", "studio_result_binding_source"):
        assert admission[name]["historical_part_scope"] is True
        assert admission[name]["current_settlement_contract"] == "studio_success_settlement_source"
