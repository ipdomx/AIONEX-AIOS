"""Source boundaries for FR-06D8C4B3 Studio process scan."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_process_scan.py"


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


def test_scan_functions_have_no_process_or_filesystem_mutation_calls():
    calls = []
    for name in ("_inventory", "_scan_proc", "_host_scan", "evaluate"):
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


def test_process_scan_requires_nofollow_and_two_pass_inventory_stability():
    source = SCRIPT.read_text()
    assert "os.O_NOFOLLOW" in source
    host = ast.unparse(_node("_host_scan"))
    assert host.count("_inventory(root)") == 3
    assert host.count("_scan_proc(identities)") == 2
    assert "visible Studio process references remain" in host


def test_success_is_studio_scoped_not_full_host_drain_or_cleanup():
    source = SCRIPT.read_text()
    for marker in (
        '"host_visible_studio_reference_scan_verified": True',
        '"studio_process_drain_verified": True',
        '"process_drain_verified": False',
        '"cleanup_authorized": False',
        '"filesystem_mutation_performed": False',
        '"full_host_closure": False',
    ):
        assert marker in source


def test_proc_scope_includes_fd_cwd_root_exe_and_mmap():
    source = ast.unparse(_node("_scan_proc"))
    for marker in ("fd", "cwd", "root", "exe", "mmap"):
        assert repr(marker) in source
    assert "map_files" in source


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
