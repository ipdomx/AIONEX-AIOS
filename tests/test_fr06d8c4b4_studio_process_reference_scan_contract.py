"""Source boundaries for FR-06D8C4B4 process-reference scan."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_process_reference_scan.py"


def _node(name):
    tree = ast.parse(SCRIPT.read_text())
    matches = [
        node
        for node in ast.walk(tree)
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


def test_scan_path_has_no_cleanup_or_process_mutations():
    calls = []
    for name in (
        "_target_identity",
        "scan_proc_references",
        "_current_epoch",
        "evaluate",
    ):
        calls.extend(_calls(_node(name)))
    forbidden = (
        ".unlink",
        ".remove",
        ".replace",
        ".rename",
        ".link",
        ".symlink",
        ".mkdir",
        ".chmod",
        ".fchmod",
        ".write",
        ".write_bytes",
        ".write_text",
        "os.kill",
        "subprocess.run",
    )
    assert not any(call.endswith(forbidden) for call in calls)


def test_receipt_scope_is_candidate_specific_not_full_process_drain():
    text = SCRIPT.read_text()
    for marker in (
        '"candidate_reference_drain_verified": True',
        '"host_process_scan_verified": True',
        '"scan_passes": 2',
        '"process_drain_verified": False',
        '"cleanup_authorized": False',
        '"filesystem_mutation_performed": False',
        '"final_deletion_permitted": False',
        '"full_host_closure": False',
    ):
        assert marker in text


def test_scan_rechecks_current_epoch_before_target_and_proc_scan():
    source = ast.unparse(_node("evaluate"))
    assert source.index("_current_epoch") < source.index("_target_identity")
    assert source.count("_target_identity") == 3
    assert source.count("scan_proc_references") == 2


def test_proc_scan_covers_each_thread_fd_cwd_root_exe_and_mmap():
    source = ast.unparse(_node("scan_proc_references"))
    for marker in ("task", "fd", "cwd", "root", "exe", "map_files", "mmap"):
        assert marker in source
    assert "process reference changed during scan" in source


def test_target_is_nofollow_and_current_final_layout_is_revalidated():
    text = SCRIPT.read_text()
    assert "os.O_NOFOLLOW" in text
    target = ast.unparse(_node("_target_identity"))
    assert "follow_symlinks=False" in ast.unparse(_node("_stat_entry"))
    assert "owned_staging_and_final_hardlinks" in target
    assert "final entry changed after candidate export" in target
    assert "hardlink layout changed after candidate export" in target


def test_cli_has_no_container_control_or_admission_mutation_commands():
    text = SCRIPT.read_text().lower()
    for forbidden in (
        "docker stop",
        "docker restart",
        "docker compose",
        "close_admission",
        "open_admission",
    ):
        assert forbidden not in text
