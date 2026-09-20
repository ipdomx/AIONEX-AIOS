"""Source invariants for FR-06D8C4B6B1 terminal-candidate export."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = (
    ROOT
    / "web-dashboard/backend/app/services/studio_crash_terminal_candidate.py"
)
PLAN = ROOT / "docs/project/PLAN.json"


def _node(name: str):
    tree = ast.parse(SERVICE.read_text())
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


def test_b6b1_export_has_no_database_filesystem_or_process_mutation():
    calls = []
    for name in (
        "_authority_payload",
        "_terminal_conflict",
        "export_terminal_candidate",
    ):
        calls.extend(_calls(_node(name)))
    forbidden = (
        ".add",
        ".add_all",
        ".delete",
        ".commit",
        ".rollback",
        ".flush",
        ".unlink",
        ".remove",
        ".rmdir",
        ".rename",
        ".replace",
        ".link",
        ".symlink",
        ".write",
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


def test_candidate_requires_valid_containment_and_rejects_terminal_conflicts():
    source = ast.unparse(_node("export_terminal_candidate"))
    assert "containment.validate_containment" in source
    assert "_terminal_conflict" in source
    assert "StudioCrashContainment" in source
    assert "StudioCrashObservation" in source
    assert "StudioExecution" in source
    assert "StudioPublication" in source


def test_candidate_keeps_historical_and_current_authority_separate():
    source = ast.unparse(_node("export_terminal_candidate"))
    for marker in (
        "'containment_operation_id'",
        "'containment_generation'",
        "'containment_boot_id'",
        "'reconciliation_authority'",
        "'reconciliation_authority_sha256'",
    ):
        assert marker in source
    authority = ast.unparse(_node("_authority_payload"))
    assert "snapshot.is_open" in authority
    assert "snapshot.operation_id is None" in authority


def test_later_closed_generation_is_allowed_but_older_is_rejected():
    source = ast.unparse(_node("export_terminal_candidate"))
    assert "authority['generation'] < original_generation" in source
    assert "authority['generation'] == original_generation" not in source


def test_candidate_never_authorizes_terminalization_or_deletion():
    text = SERVICE.read_text()
    for marker in (
        '"host_revalidation_required": True',
        '"quarantine_revalidation_required": True',
        '"terminalization_authorized": False',
        '"blocker_cleared": False',
        '"retry_authorized": False',
        '"filesystem_cleanup_claimed": False',
        '"cleanup_authorized": False',
        '"settlement_authorized": False',
        '"quarantine_deletion_permitted": False',
        '"final_deletion_permitted": False',
        '"full_host_closure": False',
    ):
        assert marker in text


def test_candidate_digest_is_bound_to_complete_output():
    source = ast.unparse(_node("export_terminal_candidate"))
    assert "candidate['candidate_sha256'] = evidence_digest(candidate)" in source


def test_b6b1_plan_is_read_only_and_nonterminal():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    item = fr06["host_state_cutover_admission"][
        "studio_crash_terminal_candidate_source"
    ]
    assert item["source_part"] == "FR-06D8C4B6B1"
    assert item["prerequisite_prs"] == [742]
    assert item["prerequisite_merged_required_before_acceptance"] is True
    assert item["database_only_read_only_export"] is True
    assert item["later_closed_maintenance_generation_permitted"] is True
    assert item["host_revalidation_required"] is True
    assert item["quarantine_revalidation_required"] is True
    for key in (
        "terminalization_authorized",
        "blocker_cleared",
        "retry_authorized",
        "filesystem_cleanup_claimed",
        "cleanup_authorized",
        "settlement_authorized",
        "quarantine_deletion_permitted",
        "final_deletion_permitted",
        "production_database_migrated",
        "production_deployment_verified",
        "full_host_closure",
    ):
        assert item[key] is False
