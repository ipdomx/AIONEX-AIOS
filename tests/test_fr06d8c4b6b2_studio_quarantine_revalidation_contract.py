"""Source invariants for FR-06D8C4B6B2 quarantine revalidation."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_quarantine_revalidation.py"
PLAN = ROOT / "docs/project/PLAN.json"


def _node(name: str):
    tree = ast.parse(SCRIPT.read_text())
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


def test_evaluate_is_studio_read_only_and_has_no_control_plane_mutation():
    calls = []
    for name in (
        "_terminal_candidate",
        "_inventory",
        "_layout",
        "_hash_descriptor",
        "_open_retained_descriptor",
        "evaluate",
    ):
        calls.extend(_calls(_node(name)))
    forbidden_suffixes = (
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
        ".chmod",
        ".chown",
        ".kill",
    )
    assert not any(call.endswith(forbidden_suffixes) for call in calls)
    source = ast.unparse(_node("evaluate"))
    for marker in (
        "open_admission",
        "close_admission",
        "docker stop",
        "docker restart",
        "docker compose",
        "renameat2",
    ):
        assert marker not in source


def test_revalidation_reacquires_container_inventory_and_proc_scan_twice():
    source = ast.unparse(_node("evaluate"))
    assert source.count("container_provider()") == 2
    assert source.count("scan.scan_proc_references") == 2
    assert source.count("_hash_descriptor") == 2
    assert "inventory_two != inventory_one" in source
    assert "source_two != source_one" in source


def test_content_authority_is_checksum_and_size_bound():
    source = SCRIPT.read_text()
    for marker in (
        '"archive_size_bytes"',
        '"archive_checksum_sha256"',
        '"content_hash_passes": 2',
        '"archive_content_revalidated": True',
        "hashlib.sha256()",
        "os.O_NOFOLLOW",
    ):
        assert marker in source


def test_inode_and_layout_are_revalidated_around_scans():
    source = ast.unparse(_node("evaluate"))
    assert source.count("_layout(") == 3
    assert "_open_retained_descriptor" in source
    assert "Studio quarantine identity changed during first scan" in source
    assert "Studio quarantine identity changed during second scan" in source
    layout = ast.unparse(_node("_layout"))
    assert "original Studio staging name reappeared" in layout
    assert "retained Studio quarantine identity changed" in layout
    assert "Studio final hardlink layout changed" in layout


def test_revalidation_never_claims_terminal_or_full_drain():
    source = SCRIPT.read_text()
    for marker in (
        '"process_drain_verified": False',
        '"authority_revalidation_required_by_next_stage": True',
        '"terminalization_authorized": False',
        '"blocker_cleared": False',
        '"retry_authorized": False',
        '"filesystem_cleanup_claimed": False',
        '"filesystem_mutation_performed": False',
        '"cleanup_authorized": False',
        '"settlement_authorized": False',
        '"quarantine_deletion_permitted": False',
        '"final_deletion_permitted": False',
        '"full_host_closure": False',
    ):
        assert marker in source


def test_current_boot_may_differ_because_state_is_freshly_revalidated():
    source = ast.unparse(_node("evaluate"))
    assert "'same_boot_as_containment'" in source
    assert "current_boot == candidate['containment_boot_id']" in source
    assert "current_boot != candidate['containment_boot_id']" not in source


def test_private_receipt_writer_is_outside_evaluate_and_create_only():
    writer = ast.unparse(_node("_write_private"))
    assert "os.O_CREAT" in writer
    assert "os.O_EXCL" in writer
    assert "os.O_NOFOLLOW" in writer
    assert "0o600" in SCRIPT.read_text()
    assert "quarantine._validated_state_root" in writer
    evaluate = ast.unparse(_node("evaluate"))
    assert "_write_private" not in evaluate


def test_b6b2_plan_is_nonterminal_and_requires_next_authority_revalidation():
    plan = json.loads(PLAN.read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    item = fr06["host_state_cutover_admission"][
        "studio_quarantine_revalidation_source"
    ]
    assert item["source_part"] == "FR-06D8C4B6B2"
    assert item["prerequisite_source_part"] == "FR-06D8C4B6B1"
    assert item["host_read_only_revalidation"] is True
    assert item["fresh_container_inventories"] == 2
    assert item["process_reference_scan_passes"] == 2
    assert item["archive_content_hash_passes"] == 2
    assert item["cross_boot_revalidation_permitted"] is True
    assert item["authority_revalidation_required_by_next_stage"] is True
    for key in (
        "terminalization_authorized",
        "blocker_cleared",
        "retry_authorized",
        "filesystem_cleanup_claimed",
        "studio_filesystem_mutation_performed",
        "cleanup_authorized",
        "settlement_authorized",
        "quarantine_deletion_permitted",
        "final_deletion_permitted",
        "production_execution_performed",
        "full_host_closure",
    ):
        assert item[key] is False
