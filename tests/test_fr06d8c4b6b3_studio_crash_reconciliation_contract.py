"""Source invariants for FR-06D8C4B6B3 terminal crash reconciliation."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (
    ROOT
    / "web-dashboard/backend/app/services/studio_crash_reconciliation.py"
)
REGISTRY = (
    ROOT
    / "web-dashboard/backend/app/services/studio_resource_registry.py"
)
MODEL = ROOT / "web-dashboard/backend/app/db/models.py"
MIGRATION = (
    ROOT
    / "web-dashboard/backend/alembic/versions/"
    "20260920_0062_studio_crash_reconciliation.py"
)
DATABASE_TEST = ROOT / "web-dashboard/backend/tests/test_database_settings.py"
PLAN = ROOT / "docs/project/PLAN.json"


def _node(path: Path, name: str):
    tree = ast.parse(path.read_text())
    matches = [
        item
        for item in ast.walk(tree)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _calls(node):
    return [
        ast.unparse(item.func)
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
    ]


def test_b6b3_service_is_database_only_and_never_mutates_host():
    calls = []
    for name in (
        "_candidate",
        "_host_receipt",
        "_expected_proof",
        "validate_reconciliation",
        "record_crash_reconciliation",
        "snapshot_crash_reconciliations",
    ):
        calls.extend(_calls(_node(SERVICE, name)))
    forbidden = (
        ".unlink",
        ".remove",
        ".rmdir",
        ".rename",
        ".replace",
        ".link",
        ".symlink",
        ".write_text",
        ".write_bytes",
        "os.open",
        "os.write",
        "os.kill",
        "subprocess.run",
    )
    assert not any(call.endswith(forbidden) for call in calls)
    text = SERVICE.read_text().lower()
    for marker in (
        "docker stop",
        "docker restart",
        "docker compose",
        "open_admission(",
        "close_admission(",
    ):
        assert marker not in text


def test_model_and_migration_define_frozen_terminal_ledger():
    model = MODEL.read_text()
    assert "class StudioCrashReconciliation(Base):" in model
    assert '__tablename__ = "studio_crash_reconciliations"' in model

    migration = MIGRATION.read_text()
    assert 'revision = "20260920_0062"' in migration
    assert 'down_revision = "20260920_0061"' in migration
    assert "studio_crash_reconciliations" in migration
    assert "no backfill" in migration.lower()
    assert "cannot be discarded by downgrade" in migration
    assert "op.drop_table" not in migration


def test_new_record_revalidates_current_closed_authority_but_exact_replay_precedes_gate():
    source = SERVICE.read_text()
    existing = source.index("existing = await session.scalar")
    authority = source.index("current = await read_admission_snapshot")
    assert existing < authority
    normalized = " ".join(source.split())
    assert "current_authority" in normalized
    assert 'checked_candidate["reconciliation_authority"]' in normalized
    assert "authority changed after host revalidation" in source


def test_terminal_proof_clears_only_blocker_and_retains_quarantine_without_retry():
    source = ast.unparse(_node(SERVICE, "_expected_proof"))
    for marker in (
        "'terminal_state': 'crash_reconciled_quarantine_retained'",
        "'terminal_reconciliation_recorded': True",
        "'terminalization_authorized': True",
        "'blocker_cleared': True",
        "'quarantine_retained': True",
        "'retry_authorized': False",
        "'filesystem_cleanup_claimed': False",
        "'filesystem_mutation_performed_by_b6b3': False",
        "'cleanup_authorized': False",
        "'settlement_authorized': False",
        "'quarantine_deletion_permitted': False",
        "'final_deletion_permitted': False",
        "'process_drain_verified': False",
        "'full_host_closure': False",
    ):
        assert marker in source


def test_registry_subtracts_only_valid_reconciliation_execution_and_observation():
    node = _node(REGISTRY, "execution_snapshot")
    assignments = [
        item
        for item in ast.walk(node)
        if isinstance(item, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "blockers"
            for target in item.targets
        )
    ]
    assert len(assignments) == 1
    blockers = ast.unparse(assignments[0].value)
    assert "len(reconciled_execution_ids)" in blockers
    assert "len(reconciled_observation_ids)" in blockers
    assert "invalid_crash_reconciliations" in blockers
    assert "contained_execution_ids" not in blockers
    assert "valid_containment_observations" not in blockers


def test_snapshot_marks_raw_crash_and_containment_reconciled_without_deleting_them():
    source = ast.unparse(_node(REGISTRY, "execution_snapshot"))
    assert "'postcrash_reconciliations'" in source
    assert "'terminal_reconciliation_recorded'" in source
    assert "'requires_reconciliation'" in source
    assert "'blocker_cleared'" in source
    assert "'crash_reconciled_terminally'" in source


def test_plan_keeps_b6b3_terminal_but_non_destructive():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    item = fr06["host_state_cutover_admission"][
        "studio_crash_terminal_reconciliation_source"
    ]
    assert item["source_part"] == "FR-06D8C4B6B3"
    assert item["migration"] == "20260920_0062"
    assert item["database_only_terminal_reconciliation"] is True
    assert (
        item[
            "valid_reconciliation_clears_execution_and_crash_observation_blockers_only"
        ]
        is True
    )
    assert item["invalid_reconciliation_clears_no_blocker"] is True
    assert item["terminalization_authorized"] is True
    assert item["blocker_cleared"] is True
    assert item["quarantine_retained"] is True
    for key in (
        "retry_authorized",
        "filesystem_cleanup_claimed",
        "studio_filesystem_mutation_performed_by_b6b3",
        "cleanup_authorized",
        "settlement_authorized",
        "quarantine_deletion_permitted",
        "final_deletion_permitted",
        "process_drain_verified",
        "production_execution_performed",
        "production_database_migrated",
        "production_deployment_verified",
        "full_host_closure",
    ):
        assert item[key] is False



def test_all_legacy_terminal_writers_fence_crash_reconciliation():
    paths = [
        ROOT / "web-dashboard/backend/app/services/studio_success_settlement.py",
        ROOT / "web-dashboard/backend/app/services/studio_prestart_cancellation.py",
        ROOT / "web-dashboard/backend/app/services/studio_poststart_cancellation.py",
    ]
    for path in paths:
        source = path.read_text()
        assert "StudioCrashReconciliation" in source
        assert "StudioCrashReconciliation.execution_id" in source


def test_backend_shipped_head_contract_advances_to_0062():
    text = DATABASE_TEST.read_text()
    assert 'frozenset({"20260920_0062"})' in text
    assert '("20260920_0061", False)' in text
    assert '("20260920_0062", True)' in text
