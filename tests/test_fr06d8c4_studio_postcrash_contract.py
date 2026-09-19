"""Source contract for read-only FR-06D8C4A crash observation."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
SERVICE = BACKEND / "app/services/studio_crash_observation.py"
REGISTRY = BACKEND / "app/services/studio_resource_registry.py"
WORKER = BACKEND / "app/services/studio_worker.py"
CONTROL = BACKEND / "app/services/studio_control_evidence.py"
MIGRATION = BACKEND / "alembic/versions/20260919_0060_studio_postcrash_observation.py"


def _node(path: Path, name: str):
    tree = ast.parse(path.read_text())
    matches = [
        node for node in ast.walk(tree)
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


def test_observer_requires_closed_admission_but_never_claims_process_drain():
    source = ast.unparse(_node(SERVICE, "observe_postcrash_state"))
    assert "read_admission_snapshot" in source
    assert "authority.is_open" in source
    text = SERVICE.read_text()
    assert '"process_drain_verified": False' in text
    assert '"cleanup_authorized": False' in text
    assert '"filesystem_mutation_performed": False' in text
    assert '"full_host_closure": False' in text


def test_observer_has_no_filesystem_mutation_or_retry_calls():
    calls = _calls(ast.parse(SERVICE.read_text()))
    forbidden = (
        ".unlink", ".remove", ".replace", ".rename", ".link", ".symlink",
        ".mkdir", ".write", ".write_bytes", ".chmod", ".fchmod",
        ".run_in_executor", ".to_thread",
    )
    assert not any(call.endswith(forbidden) for call in calls)
    observe_calls = _calls(_node(SERVICE, "observe_postcrash_state"))
    assert not any("retry" in call.lower() for call in observe_calls)


def test_observer_walks_directory_descriptors_without_following_symlinks():
    text = SERVICE.read_text()
    assert "os.O_NOFOLLOW" in text and "dir_fd=directory" in text
    assert "follow_symlinks=False" in text
    assert "resolve(" not in text


def test_crash_observation_is_a_replay_fence_but_not_terminal_settlement():
    for path, name in (
        (WORKER, "_claim"),
        (REGISTRY, "register_claim"),
        (REGISTRY, "begin_registered"),
        (CONTROL, "has_retained_studio_evidence"),
    ):
        assert "StudioCrashObservation" in ast.unparse(_node(path, name))
    snapshot = ast.unparse(_node(REGISTRY, "execution_snapshot"))
    assert "postcrash_observation_count" in snapshot
    assert "requires_reconciliation" not in snapshot or "snapshot_crash_observations" in snapshot


def test_migration_is_additive_frozen_and_refuses_downgrade():
    text = MIGRATION.read_text()
    assert 'revision = "20260919_0060"' in text
    assert 'down_revision = "20260919_0059"' in text
    assert "frozen schema" in text
    assert "from app." not in text
    assert any(
        isinstance(node, ast.Raise)
        for node in ast.walk(_node(MIGRATION, "downgrade"))
    )


def test_project_plan_keeps_cleanup_and_production_boundaries_false():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    contract = fr06["host_state_cutover_admission"][
        "studio_postcrash_observation_source"
    ]
    assert contract["migration"] == "20260919_0060"
    assert contract["filesystem_mutation_performed"] is False
    assert contract["cleanup_authorized"] is False
    assert contract["process_drain_verified"] is False
    assert contract["production_deployment_verified"] is False
    assert contract["full_host_closure"] is False
