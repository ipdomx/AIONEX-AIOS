"""Source invariants for FR-06D8C4B6A crash-containment provenance."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "web-dashboard/backend/app/services/studio_crash_containment.py"
REGISTRY = ROOT / "web-dashboard/backend/app/services/studio_resource_registry.py"
MODEL = ROOT / "web-dashboard/backend/app/db/models.py"
MIGRATION = (
    ROOT
    / "web-dashboard/backend/alembic/versions"
    / "20260920_0061_studio_crash_containment.py"
)
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


def test_b6a_recording_has_no_filesystem_process_or_container_mutations():
    calls = []
    for name in (
        "_process_receipt",
        "_quarantine_receipt",
        "_expected_proof",
        "validate_containment",
        "record_crash_containment",
        "snapshot_crash_containments",
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
        ".chmod",
        ".fchmod",
        ".chown",
        ".fchown",
        ".mkdir",
        ".write_text",
        ".write_bytes",
        "os.open",
        "os.write",
        "os.kill",
        "subprocess.run",
    )
    assert not any(call.endswith(forbidden) for call in calls)
    text = SERVICE.read_text().lower()
    for forbidden_text in (
        "docker stop",
        "docker restart",
        "docker compose",
        "open_admission(",
        "close_admission(",
    ):
        assert forbidden_text not in text


def test_b6a_requires_full_b3_b4_b5_chain_and_exact_digests():
    source = ast.unparse(_node(SERVICE, "record_crash_containment"))
    for marker in (
        "cleanup_candidate",
        "process_scan_receipt",
        "staging_quarantine_receipt",
        "_candidate_input",
        "_process_receipt",
        "_quarantine_receipt",
        "_reconstruct_candidate",
        "_expected_proof",
    ):
        assert marker in source
    assert "reconstructed != candidate_input" in source

    process = ast.unparse(_node(SERVICE, "_process_receipt"))
    quarantine = ast.unparse(_node(SERVICE, "_quarantine_receipt"))
    assert "_receipt_digest" in process
    assert "_receipt_digest" in quarantine
    assert "process_scan_receipt_sha256" in quarantine
    assert "candidate_sha256" in process
    assert "candidate_sha256" in quarantine


def test_exact_existing_chain_is_idempotent_before_current_authority_gate():
    source = ast.unparse(_node(SERVICE, "record_crash_containment"))
    existing = source.index("existing = await session.scalar")
    authority = source.index("authority = await read_admission_snapshot")
    assert existing < authority
    assert "existing.proof != expected" in source
    assert "return existing" in source


def test_b6a_proof_never_claims_cleanup_retry_settlement_or_blocker_clear():
    source = SERVICE.read_text()
    for marker in (
        '"filesystem_cleanup_claimed": False',
        '"blocker_cleared": False',
        '"retry_authorized": False',
        '"process_drain_verified": False',
        '"cleanup_authorized": False',
        '"settlement_authorized": False',
        '"quarantine_deletion_permitted": False',
        '"final_deletion_permitted": False',
        '"full_host_closure": False',
    ):
        assert marker in source


def test_snapshot_is_diagnostic_and_never_returns_terminal_authority():
    source = ast.unparse(_node(SERVICE, "snapshot_crash_containments"))
    assert "'requires_reconciliation': True" in source
    assert "'blocker_cleared': False" in source
    assert "'retry_authorized': False" in source
    assert "'cleanup_authorized': False" in source
    assert "'settlement_authorized': False" in source


def test_registry_reports_containment_without_subtracting_it_from_blockers():
    source = REGISTRY.read_text()
    assert "snapshot_crash_containments" in source
    assert '"postcrash_containments": crash_containments' in source
    assert '"postcrash_containment_recorded"' in source
    block_node = _node(REGISTRY, "execution_snapshot")
    block_source = ast.unparse(block_node)
    # Containment can annotate evidence, but the blockers expression must not
    # subtract contained execution/observation sets.
    blockers_assignments = [
        item
        for item in ast.walk(block_node)
        if isinstance(item, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "blockers"
            for target in item.targets
        )
    ]
    assert len(blockers_assignments) == 1
    blockers = ast.unparse(blockers_assignments[0].value)
    assert "contained_execution_ids" not in blockers
    assert "valid_containment_observations" not in blockers
    assert "crash_containments" not in blockers
    assert "len(crash_observations)" in blockers
    assert "blockers == 0" in block_source


def test_model_and_migration_define_immutable_containment_ledger():
    model = MODEL.read_text()
    assert 'class StudioCrashContainment(Base):' in model
    assert '__tablename__ = "studio_crash_containments"' in model
    migration = MIGRATION.read_text()
    assert 'revision = "20260920_0061"' in migration
    assert 'down_revision = "20260919_0060"' in migration
    normalized_migration = " ".join(migration.lower().split())
    assert "production activation" in normalized_migration
    assert "no backfill" in migration.lower()
    assert "cannot be discarded by downgrade" in migration


def test_b6a_plan_keeps_containment_nonterminal():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    source = fr06["host_state_cutover_admission"]["studio_crash_containment_source"]
    assert source["source_part"] == "FR-06D8C4B6A"
    assert source["source_implementation_present"] is True
    assert source["blocker_cleared"] is False
    assert source["retry_authorized"] is False
    assert source["cleanup_authorized"] is False
    assert source["settlement_authorized"] is False
    assert source["quarantine_deletion_permitted"] is False
    assert source["final_deletion_permitted"] is False
    assert source["production_database_migrated"] is False
    assert source["production_deployment_verified"] is False
    assert source["full_host_closure"] is False
