"""The canonical report must never equate merge or old load evidence with release."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("project_hub", ROOT / "scripts/project_hub.py")
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)


@pytest.fixture
def plan():
    return hub.load_plan(ROOT)


def receipt(batch="FR-00"):
    return {"event_id": "test-" + batch, "batch_id": batch, "status": "complete", "summary_ar": "إيصال اختبار فقط", "merge_commit": "a" * 40, "protected_checks_passed": True, "protected_check_count": 12, "verification_passed": True, "deployment_verified": True, "evidence": ["isolated-test-evidence"]}


def test_complete_registry_and_all_findings_have_owners(plan):
    hub.validate_plan(plan)
    assert len(plan["capabilities"]) == 62
    assert len(plan["batches"]) == 26
    assert len(plan["audit_findings"]) == 18


def test_cannot_silently_drop_a_capability(plan):
    plan["capabilities"].pop()
    with pytest.raises(ValueError):
        hub.validate_plan(plan)


def test_cannot_weaken_multi_project_acceptance(plan):
    plan["capacity_acceptance"]["conversations_per_user_min"] = 1
    with pytest.raises(ValueError):
        hub.validate_plan(plan)


def test_cannot_add_unapproved_deferred_scope(plan):
    plan["owner_decisions"]["deferred"].append("all security")
    with pytest.raises(ValueError):
        hub.validate_plan(plan)


@pytest.mark.parametrize("field", ["merge_commit", "protected_checks_passed", "verification_passed", "evidence"])
def test_completion_requires_evidence(plan, field):
    event = receipt()
    event.pop(field)
    with pytest.raises(ValueError):
        hub.current_state(plan, [event])


def test_merge_alone_is_not_deployment(plan):
    event = receipt("FR-01")
    event["deployment_verified"] = False
    with pytest.raises(ValueError, match="merge alone"):
        hub.current_state(plan, [receipt(), event])


def test_release_requires_all_predecessors(plan):
    with pytest.raises(ValueError, match="unfinished prerequisite"):
        hub.current_state(plan, [receipt("FR-25")])


def test_historical_1000_admission_is_not_expanded_acceptance(plan):
    states = {b["id"]: {"status": "complete"} for b in plan["batches"]}
    event = receipt("FR-09")
    event["capacity_result"] = {"authenticated_active_users": 1000}
    with pytest.raises(ValueError, match="expanded capacity"):
        hub.apply_event(plan, states, event)


def test_capacity_error_budget_cannot_be_omitted(plan):
    states = {b["id"]: {"status": "complete"} for b in plan["batches"]}
    event = receipt("FR-09")
    event["capacity_result"] = copy.deepcopy(plan["capacity_acceptance"])
    event["capacity_result"].pop("unexpected_error_rate_max")
    with pytest.raises(ValueError, match="SLO"):
        hub.apply_event(plan, states, event)


def test_record_is_idempotent_and_current_report_is_generated(plan, tmp_path):
    directory = tmp_path / "docs/project"
    directory.mkdir(parents=True)
    (directory / "PLAN.json").write_text(json.dumps(plan))
    event = receipt()
    first = hub.record(tmp_path, event)
    second = hub.record(tmp_path, event)
    assert first["next_batch"] == second["next_batch"] == "FR-01"
    assert len(hub.read_events(tmp_path)) == 1
    assert (directory / "PROJECT-REPORT.md").is_file()
    assert first["release_status"] == "FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED"


def test_conflicting_replay_is_rejected(plan, tmp_path):
    directory = tmp_path / "docs/project"
    directory.mkdir(parents=True)
    (directory / "PLAN.json").write_text(json.dumps(plan))
    event = receipt()
    hub.record(tmp_path, event)
    event["summary_ar"] = "different"
    with pytest.raises(ValueError, match="conflicting"):
        hub.record(tmp_path, event)


def test_all_remaining_batches_have_short_parts_and_preserve_scope(plan):
    assert "short_parts" in plan["owner_decisions"]
    for batch in plan["batches"][2:]:
        parts = batch["sub_batches"]
        assert 3 <= len(parts) <= 6
        identifiers = [part.split(" ", 1)[0] for part in parts]
        assert len(identifiers) == len(set(identifiers))
        assert all(name.startswith(batch["id"]) for name in identifiers)
    assert len(plan["owner_decisions"]["deferred"]) == 4
    assert plan["capacity_acceptance"]["authenticated_active_users"] == 1000
