"""Source boundaries for FR-06D8C4B3 cleanup candidate export."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "web-dashboard/backend/app/services/studio_cleanup_candidate.py"


def _node(name):
    tree = ast.parse(SERVICE.read_text())
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


def test_export_has_no_filesystem_or_business_mutation_calls():
    calls = _calls(_node("export_cleanup_candidate"))
    forbidden = (
        ".unlink",
        ".remove",
        ".replace",
        ".rename",
        ".link",
        ".mkdir",
        ".write_text",
        ".write_bytes",
        ".commit",
        ".delete",
        ".update",
    )
    assert not any(call.endswith(forbidden) for call in calls)


def test_candidate_never_authorizes_final_deletion_or_cleanup():
    text = SERVICE.read_text()
    assert '"final_deletion_permitted": False' in text
    assert '"cleanup_authorized": False' in text
    assert '"filesystem_mutation_performed": False' in text
    assert '"full_host_closure": False' in text


def test_only_bounded_observed_layouts_are_exportable():
    source = SERVICE.read_text()
    for layout in (
        "no_archive_entry",
        "owned_staging_present",
        "owned_final_present",
        "owned_staging_and_final_hardlinks",
    ):
        assert layout in source
    assert "entry_identity_conflict" not in ast.unparse(_node("_candidate"))
    assert "directory_identity_conflict" not in ast.unparse(_node("_candidate"))


def test_candidate_exports_relative_components_not_absolute_root():
    source = ast.unparse(_node("_candidate"))
    assert "relative_components" in source
    assert '"root"' not in source
    assert "final_deletion_permitted" in source


def test_project_plan_keeps_cleanup_candidate_nonmutating():
    import json

    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    contract = fr06["host_state_cutover_admission"]["studio_cleanup_candidate_source"]
    assert contract["source_part"] == "FR-06D8C4B3"
    assert contract["relative_components_only"] is True
    assert contract["final_deletion_permitted"] is False
    assert contract["cleanup_authorized"] is False
    assert contract["filesystem_mutation_performed"] is False
    assert contract["full_host_closure"] is False
