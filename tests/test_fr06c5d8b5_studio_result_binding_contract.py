"""Output binding is separate from resource settlement and production rollout."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "web-dashboard/backend/app/services"


def test_binding_runs_before_any_business_asset_or_revision_creation():
    tree = ast.parse((SERVICES / "studio_worker.py").read_text())
    worker = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StudioWorker")
    execute = next(node for node in worker.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_execute_claimed")
    calls = [node for node in ast.walk(execute) if isinstance(node, ast.Call)]
    binding = [node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "bind_owned_result"]
    assert len(binding) == 1
    business = [node for node in calls if isinstance(node.func, ast.Name) and node.func.id in {"StudioAsset", "StudioAssetRevision"}]
    assert len(business) == 2 and all(binding[0].lineno < node.lineno for node in business)
    assert "revision_id=revision_id" in ast.unparse(binding[0])


def test_binding_preserves_caller_transaction_without_filesystem_side_effects():
    tree = ast.parse((SERVICES / "studio_result_binding.py").read_text())
    attributes = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not attributes.intersection({"commit", "rollback", "flush", "add", "delete", "unlink", "remove", "mkdir", "write_bytes", "open", "resolve"})
    source = ast.unparse(tree)
    assert "session.no_autoflush" in source
    assert "with_for_update()" in source and "populate_existing=True" in source
    assert "require_admission_open" not in source


def test_business_records_retain_binding_and_stale_revision_is_rejected():
    source = (SERVICES / "studio_worker.py").read_text()
    assert source.count("studio_result_binding.BINDING_KEY: deepcopy(binding)") == 4
    assert "asset.current_revision != revision_number - 1" in source
    assert "id=revision_id" in source


def test_public_binding_excludes_raw_nonce_storage_path_and_user_payload():
    tree = ast.parse((SERVICES / "studio_result_binding.py").read_text())
    method = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "bind_owned_result")
    results = [node.value for node in ast.walk(method) if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)]
    assert len(results) == 1
    keys = {key.value for key in results[0].keys if isinstance(key, ast.Constant)}
    assert not keys.intersection({"nonce", "ownership_nonce", "storage_path", "root", "brief", "content"})
    assert {"publication_id", "execution_id", "revision_id", "publication_evidence_sha256", "file_identity_sha256", "thread_evidence_sha256"} <= keys


def test_binding_does_not_claim_resource_or_host_settlement():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    part = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")["host_state_cutover_admission"]["studio_result_binding_source"]
    assert part["same_transaction_business_binding"] is True
    assert part["prerequisite_merged_prs"] == [729]
    for key in ("execution_settlement_implemented", "post_crash_cleanup_implemented", "production_deployment_verified", "production_database_migrated", "full_host_closure"):
        assert part[key] is False
    assert part["additional_migration_required"] is False


def test_result_binding_keeps_existing_no_replay_and_snapshot_invariants():
    source = (SERVICES / "studio_resource_registry.py").read_text()
    assert 'row.state = "unresolved"' in source
    assert '"full_host_closure": False' in source
    assert '"cleanup_verified": False' in source
    assert "prior_publication is not None" in source
