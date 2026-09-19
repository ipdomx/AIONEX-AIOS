"""Source boundaries for FR-06D8C3 post-start Studio cancellation."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "web-dashboard/backend"
SERVICE = BACKEND / "app/services/studio_poststart_cancellation.py"
WORKER = BACKEND / "app/services/studio_worker.py"
REGISTRY = BACKEND / "app/services/studio_resource_registry.py"
CONTROL = BACKEND / "app/services/studio_control_evidence.py"
MIGRATION = (
    BACKEND
    / "alembic/versions/20260919_0059_studio_poststart_cancellation.py"
)


def _node(path: Path, name: str):
    tree = ast.parse(path.read_text())
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


def test_worker_settles_only_internal_resource_cancellation_after_stop_evidence():
    source = ast.unparse(_node(WORKER, "execute"))
    assert (
        source.index("await studio_registry.observe_execution_end")
        < source.index("await self._mark_unresolved")
        < source.index(
            "await studio_poststart_cancellation.settle_poststart_cancellation"
        )
    )
    assert "isinstance(exc, studio_registry.StudioResourceCancelled)" in source
    assert "return" in source
    # Generic caller cancellation remains outside the internal subtype branch.
    assert "asyncio.CancelledError" not in source


def test_terminal_qualification_requires_joined_success_or_no_resources():
    source = ast.unparse(_node(SERVICE, "_qualify_resources"))
    assert "item['state'] != 'joined'" in source
    assert "item['outcome'] != 'success'" in source
    for mode in (
        "started_no_payload_resource",
        "joined_build_before_storage",
        "complete_publication_retained",
    ):
        assert mode in source
    assert "publication.state != 'observed'" in source
    assert "journal.validate_row(publication)" in source


def test_settlement_has_no_filesystem_effect_retry_loop_or_host_closure_claim():
    tree = ast.parse(SERVICE.read_text())
    calls = _calls(tree)
    forbidden = (
        ".unlink",
        ".remove",
        ".replace",
        ".write_bytes",
        ".mkdir",
        ".run_in_executor",
        ".to_thread",
    )
    assert not any(call.endswith(forbidden) for call in calls)
    assert not any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(
        _node(SERVICE, "settle_poststart_cancellation")
    ))
    text = SERVICE.read_text()
    assert '"filesystem_cleanup_claimed": False' in text
    assert '"full_host_closure": False' in text
    assert '"accepted_archive_retained": archive_retained' in text


def test_replay_and_control_paths_include_poststart_receipt():
    worker_claim = ast.unparse(_node(WORKER, "_claim"))
    register = ast.unparse(_node(REGISTRY, "register_claim"))
    begin = ast.unparse(_node(REGISTRY, "begin_registered"))
    control = ast.unparse(_node(CONTROL, "has_retained_studio_evidence"))
    for source in (worker_claim, register, begin, control):
        assert "StudioPoststartCancellation" in source


def test_snapshot_distinguishes_poststart_receipts_from_success_and_prestart():
    source = ast.unparse(_node(REGISTRY, "execution_snapshot"))
    for marker in (
        "snapshot_poststart_cancellations",
        "poststart_cancelled_count",
        "invalid_poststart_cancellation_count",
        "cancelled_after_execution_start",
        "cancelled_archive_retained",
    ):
        assert marker in source
    assert "full_host_closure" in source


def test_migration_is_additive_frozen_and_refuses_destructive_downgrade():
    text = MIGRATION.read_text()
    assert 'revision = "20260919_0059"' in text
    assert 'down_revision = "20260919_0058"' in text
    assert "frozen schema" in text
    assert "from app." not in text
    upgrade_calls = _calls(_node(MIGRATION, "upgrade"))
    assert not any(call.endswith((".delete", ".update")) for call in upgrade_calls)
    assert any(
        isinstance(node, ast.Raise)
        for node in ast.walk(_node(MIGRATION, "downgrade"))
    )


def test_project_plan_keeps_operational_boundaries_false():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    fr06 = next(batch for batch in plan["batches"] if batch["id"] == "FR-06")
    contract = fr06["host_state_cutover_admission"][
        "studio_poststart_cancellation_source"
    ]
    assert contract["migration"] == "20260919_0059"
    assert contract["joined_resources_required"] is True
    assert contract["partial_publication_accepted"] is False
    assert contract["accepted_archive_deleted"] is False
    for key in (
        "post_crash_cleanup_implemented",
        "production_deployment_verified",
        "production_database_migrated",
        "full_host_closure",
    ):
        assert contract[key] is False
