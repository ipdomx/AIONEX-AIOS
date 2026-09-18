"""Reviewed source boundaries; functional ownership proof uses PostgreSQL tests."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
SERVICES = BACKEND / "app/services"


def test_studio_ledger_cannot_disappear_with_business_rows():
    tree = ast.parse((BACKEND / "app/db/models.py").read_text())
    model = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StudioExecution")
    calls = [node for node in ast.walk(model) if isinstance(node, ast.Call)]
    assert not any(isinstance(node.func, ast.Name) and node.func.id == "ForeignKey" for node in calls)
    source = ast.unparse(model)
    assert "cleanup_verified = false" in source
    assert "unique=True" in source and "job_id" in source


def test_studio_resource_intent_precedes_thread_submission():
    source = (SERVICES / "studio_resource_registry.py").read_text()
    assert source.index("owner, resource_id = await reserve_thread(") < source.index("result = await joined_studio_thread(call)")
    assert 'joined=finished.is_set() and not isinstance(original, StudioThreadUncertain)' in source
    assert 'original.add_note(' in source
    assert 'type(evidence_error).__name__' in source
    assert '"cleanup_verified": True' not in source


def test_studio_worker_retains_output_instead_of_path_only_deletion():
    source = (SERVICES / "studio_worker.py").read_text()
    assert "studio_registry.register_claim(" in source
    assert "studio_registry.begin_registered(" in source
    assert source.count("studio_registry.owned_studio_thread(") == 2
    tree = ast.parse(source)
    worker = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StudioWorker")
    # A lexical substring also matches test_path.unlink() in preflight. Forbid
    # path deletion in every worker method except that private health probe.
    for method in worker.body:
        if isinstance(method, (ast.AsyncFunctionDef, ast.FunctionDef)) and method.name != "preflight":
            assert not any(
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "unlink" for node in ast.walk(method)
            )
    assert "Studio artifact retained for owned reconciliation" in source


def test_snapshot_keeps_all_generations_and_never_asserts_host_closure():
    source = (SERVICES / "studio_resource_registry.py").read_text()
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "execution_snapshot")
    body = ast.get_source_segment(source, node)
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" in body
    assert 'select(StudioExecution).order_by' in body
    assert '"coverage_unverified": True, "full_host_closure": False' in body
    assert "ownership_nonce" not in body
    assert "admitted_generation ==" not in body


def test_migration_is_frozen_and_rejects_erasure():
    source = (BACKEND / "alembic/versions/20260918_0055_studio_execution_resources.py").read_text()
    assert 'down_revision = "20260918_0054"' in source
    assert "from app." not in source
    assert '"columns"' in source and '"foreign_keys"' in source
    assert "frozen schema" in source
    assert "Execution evidence cannot be discarded by downgrade" in source


def test_project_plan_keeps_source_acceptance_separate_from_settlement():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    batch = next(item for item in plan["batches"] if item["id"] == "FR-06")
    def locate(value):
        if isinstance(value, dict):
            if "studio_execution_resources_source" in value:
                return value["studio_execution_resources_source"]
            for child in value.values():
                found = locate(child)
                if found is not None:
                    return found
        return None
    contract = locate(batch)
    assert contract is not None
    assert contract["source_implementation_present"] is True
    assert contract["migration"] == "20260918_0055"
    assert contract["snapshot_isolation"] == "repeatable_read"
    for key in (
        "uncertain_executor_is_join_proof", "automatic_uncertain_requeue",
        "filesystem_identity_registry_implemented", "filesystem_cleanup_implemented",
        "execution_settlement_implemented", "production_database_migrated",
        "production_deployment_verified", "coverage_verified", "full_host_closure",
    ):
        assert contract[key] is False
