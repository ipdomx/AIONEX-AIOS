"""Repository-level boundaries for the not-yet-wired execution registry."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
SERVICE = BACKEND / "app/services/host_maintenance_scan_execution.py"
MIGRATION = BACKEND / "alembic/versions/20260918_0053_scan_execution_ownership.py"


def _function(path, name):
    tree = ast.parse(path.read_text())
    return next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def test_claim_and_begin_do_not_hide_a_caller_commit():
    for name in ("register_execution", "begin_execution"):
        node = _function(SERVICE, name)
        calls = [item.func for item in ast.walk(node) if isinstance(item, ast.Call)]
        assert not any(isinstance(call, ast.Attribute) and call.attr in {"commit", "rollback"} for call in calls)
        assert any(isinstance(call, ast.Name) and call.id == "require_scan_admission" for call in calls)


def test_registry_does_not_perform_runtime_io_or_automatic_replay():
    source = SERVICE.read_text()
    assert "create_subprocess" not in source and "to_thread(" not in source
    assert "run_zap(" not in source and "httpx" not in source
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" in source
    assert '"full_host_closure": False' in source
    assert '"coverage_unverified": True' in source


def test_new_execution_model_preserves_orphan_evidence_and_supervisor_join():
    tree = ast.parse((BACKEND / "app/db/models.py").read_text())
    node = next(item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == "SecurityScanExecution")
    fields = {item.target.id for item in node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}
    assert {"scan_id", "resources", "ownership_nonce", "operation_stopped_at", "supervisor_stopped_at", "settled_at", "zap_owner_key"} <= fields
    assert not any(isinstance(item, ast.Call) and isinstance(item.func, ast.Name) and item.func.id == "ForeignKey" for item in ast.walk(node))


def test_downgrade_explicitly_refuses_to_discard_ledger():
    node = _function(MIGRATION, "downgrade")
    assert any(isinstance(item, ast.Raise) for item in node.body)
    source = ast.get_source_segment(MIGRATION.read_text(), node)
    assert "drop_table" not in source
    assert 'down_revision = "20260917_0052"' in MIGRATION.read_text()


def test_receipt_and_worker_do_not_claim_runtime_wiring():
    receipt = (ROOT / "docs/project/receipts/FR-06C5D7B3-scan-execution-registry.md").read_text()
    worker = (BACKEND / "app/services/security_scan_worker.py").read_text()
    assert "The existing worker does not call these helpers" in receipt
    assert "synthetic inputs" in receipt
    assert "No new HTTP cancellation route" in receipt
    # When the next part genuinely wires the worker, replace this temporary
    # boundary with actual runtime/cancellation acceptance, not a fake pass.
    assert "host_maintenance_scan_execution" not in worker
