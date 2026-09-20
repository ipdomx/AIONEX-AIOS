"""Source boundaries for FR-06D8C4B5 retained Studio staging quarantine."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_staging_quarantine.py"


def _tree():
    return ast.parse(SCRIPT.read_text())


def _node(name):
    matches = [
        node
        for node in ast.walk(_tree())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _calls(node):
    return [
        ast.unparse(item.func)
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
    ]


def test_quarantine_path_has_no_destructive_cleanup_or_final_mutation():
    calls = []
    for name in (
        "_layout",
        "_zero_references",
        "evaluate_and_quarantine",
        "_rename_noreplace",
    ):
        calls.extend(_calls(_node(name)))
    forbidden = (
        ".unlink",
        ".remove",
        ".rmdir",
        ".replace",
        ".link",
        ".symlink",
        ".chmod",
        ".fchmod",
        ".chown",
        ".fchown",
        ".truncate",
        ".ftruncate",
        "os.kill",
        "subprocess.run",
    )
    assert not any(call.endswith(forbidden) for call in calls)


def test_studio_namespace_mutation_is_only_atomic_noreplace_rename():
    source = ast.unparse(_node("evaluate_and_quarantine"))
    assert source.count("_rename_noreplace") == 1
    for forbidden in ("os.rename", "os.replace", "os.unlink", "Path.unlink"):
        assert forbidden not in source
    rename_source = ast.unparse(_node("_rename_noreplace"))
    assert "renameat2" in rename_source
    assert "_RENAME_NOREPLACE" in rename_source
    assert "os.rename" not in rename_source
    assert "os.replace" not in rename_source


def test_quarantine_name_is_deterministic_and_candidate_digest_bound():
    source = ast.unparse(_node("_quarantine_name"))
    assert ".studio-quarantine-" in source
    assert "candidate_sha256" in source
    assert ".retained" in source
    assert "uuid" not in source.lower()
    assert "random" not in source.lower()


def test_receipt_never_claims_cleanup_settlement_deletion_or_full_drain():
    text = SCRIPT.read_text()
    for marker in (
        '"process_drain_verified": False',
        '"cleanup_authorized": False',
        '"settlement_authorized": False',
        '"quarantine_deletion_permitted": False',
        '"final_deletion_permitted": False',
        '"full_host_closure": False',
        '"filesystem_mutation_performed": True',
        '"staging_namespace_detached": True',
        '"quarantine_inode_retained": True',
        '"final_layout_preserved": True',
    ):
        assert marker in text


def test_b5_consumes_exact_b4_receipt_and_same_boot_boundary():
    source = ast.unparse(_node("_scan_receipt"))
    for marker in (
        "SCAN_SCHEMA",
        "writer_receipt_sha256",
        "runtime_receipt_sha256",
        "candidate_sha256",
        "operation_id",
        "generation",
        "boot_id",
        "candidate_reference_drain_verified",
        "host_process_scan_verified",
        "visible_reference_count",
        "staging_identity",
    ):
        assert marker in source
    assert "value['boot_id'] != boot_id" in source


def test_b5_rechecks_current_epoch_and_proc_references_around_mutation():
    source = ast.unparse(_node("evaluate_and_quarantine"))
    assert source.count("current_epoch()") >= 4
    helper = ast.unparse(_node("current_epoch"))
    assert "container_provider()" in helper
    assert "scan._current_epoch" in helper
    assert source.count("_zero_references") == 4
    rename = source.index("_rename_noreplace")
    assert source.index("_zero_references") < rename
    assert source.rindex("_zero_references") > rename


def test_recovery_requires_exact_deterministic_quarantine_inode():
    source = ast.unparse(_node("_layout"))
    assert "staging is not None and quarantine is not None" in source
    assert "scan._same_identity(expected, quarantine)" in source
    evaluate = ast.unparse(_node("evaluate_and_quarantine"))
    assert "recovered = True" in evaluate
    assert "'recovered_existing_quarantine': recovered" in evaluate


def test_no_container_control_database_or_admission_mutation_surface():
    text = SCRIPT.read_text().lower()
    for forbidden in (
        "docker stop",
        "docker restart",
        "docker compose",
        "sqlalchemy",
        "sessionlocal",
        "close_admission",
        "open_admission",
        "settle_execution",
        "retry_execution",
    ):
        assert forbidden not in text


def test_private_receipt_content_is_exact_and_self_digest_verified():
    source = ast.unparse(_node("_validated_output_receipt"))
    assert "_RECEIPT_KEYS" in source
    assert "candidate_sha256" in source
    assert "_quarantine_name(candidate_sha256)" in source
    assert "receipt_sha256" in source
    assert "_sha(body)" in source
    for marker in (
        "staging_namespace_detached",
        "quarantine_inode_retained",
        "final_layout_preserved",
        "cleanup_authorized",
        "settlement_authorized",
        "quarantine_deletion_permitted",
        "final_deletion_permitted",
        "full_host_closure",
    ):
        assert marker in source


def test_receipt_persistence_is_fixed_private_create_only_state():
    source = ast.unparse(_node("_write_private"))
    root = ast.unparse(_node("_validated_state_root"))
    text = SCRIPT.read_text()
    assert "os.O_EXCL" in source
    assert "os.O_CREAT" in source
    assert "os.O_NOFOLLOW" in root
    assert "dir_fd=current" in root
    assert "0o600" in text
    assert "0o700" in text
    assert "STATE_ROOT" in text
    assert "/var/lib/aionex/fr06d8c4b5-studio-quarantine" in text
    assert ".mkdir(" not in source
    assert ".mkdir(" not in root
    assert "candidate_sha256" in source
    assert "st_nlink" in source


def test_project_plan_keeps_b5_as_retained_containment_not_cleanup():
    import json

    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    contract = fr06["host_state_cutover_admission"][
        "studio_staging_quarantine_source"
    ]
    assert contract["source_part"] == "FR-06D8C4B5"
    assert contract["prerequisite_merged_prs"] == [740]
    assert contract["same_boot_as_process_scan_required"] is True
    assert contract["fresh_container_inventory_rechecks_mutation_path"] == 4
    assert contract["fresh_container_inventory_rechecks_recovery_path"] == 3
    assert contract["atomic_rename_noreplace_required"] is True
    assert contract["pre_quarantine_proc_scans"] == 2
    assert contract["post_quarantine_proc_scans"] == 2
    assert contract["quarantine_inode_retained"] is True
    assert contract["private_receipt_state_root"] == (
        "/var/lib/aionex/fr06d8c4b5-studio-quarantine"
    )
    assert contract["state_root_descriptor_chain_nofollow"] is True
    assert contract["receipt_create_only"] is True
    assert contract["receipt_single_link_required"] is True
    assert contract["receipt_exact_schema_required"] is True
    assert contract["receipt_self_digest_verified_before_write"] is True
    assert contract["receipt_candidate_digest_match_required"] is True
    assert contract["receipt_quarantine_name_match_required"] is True
    assert contract["production_mutation_performed"] is False
    assert contract["process_drain_verified"] is False
    assert contract["cleanup_authorized"] is False
    assert contract["settlement_authorized"] is False
    assert contract["quarantine_deletion_permitted"] is False
    assert contract["final_deletion_permitted"] is False
    assert contract["full_host_closure"] is False
