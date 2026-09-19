"""Source boundaries for FR-06D8C4B2 Studio runtime drain."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/security/fr06d8c4_studio_runtime_drain.py"


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


def test_evaluator_does_not_mutate_host_database_or_filesystem():
    calls = _calls(_node("evaluate"))
    forbidden = (
        ".unlink",
        ".remove",
        ".replace",
        ".rename",
        ".link",
        ".mkdir",
        ".write_text",
        ".write_bytes",
        "subprocess.run",
    )
    assert not any(call.endswith(forbidden) for call in calls)


def test_runtime_drain_still_refuses_cleanup_authority():
    text = SCRIPT.read_text()
    for marker in (
        '"backup_cycle_drain_verified": True',
        '"process_drain_verified": False',
        '"host_process_scan_verified": False',
        '"cleanup_authorized": False',
        '"filesystem_mutation_performed": False',
        '"full_host_closure": False',
    ):
        assert marker in text


def test_same_operation_generation_and_container_epoch_are_required():
    source = ast.unparse(_node("evaluate"))
    assert "runtime writer container changed" in source
    assert "runtime writer restart count changed" in source
    backup = ast.unparse(_node("_backup_snapshot"))
    assert "operation_id" in backup and "generation" in backup
    assert "backup snapshot predates writer-epoch receipt" in backup


def test_cli_has_no_container_control_commands():
    text = SCRIPT.read_text().lower()
    for forbidden in (
        "docker stop",
        "docker restart",
        "docker compose",
        "close_admission",
        "open_admission",
    ):
        assert forbidden not in text
