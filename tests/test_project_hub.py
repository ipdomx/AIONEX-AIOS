"""The canonical report must never equate merge or old load evidence with release."""
from __future__ import annotations

import copy
import fcntl
import importlib.util
import json
import multiprocessing
from pathlib import Path
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("project_hub", ROOT / "scripts/project_hub.py")
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)


def hold_partial_journal(root, payload, ready):
    directory = Path(root) / "docs/project/runtime"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".journal.lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        path = directory / "events.jsonl"
        midpoint = len(payload) // 2
        path.write_text(payload[:midpoint], encoding="utf-8")
        ready.set()
        time.sleep(0.3)
        path.write_text(payload, encoding="utf-8")


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


def test_validate_waits_for_inflight_journal_write(plan, tmp_path):
    directory = tmp_path / "docs/project"
    directory.mkdir(parents=True)
    (directory / "PLAN.json").write_text(json.dumps(plan))
    event = {
        "event_id": "test-partial-read",
        "batch_id": "FR-00",
        "status": "in_progress",
        "summary_ar": "إيصال اختبار فقط",
    }
    payload = json.dumps(event) + "\n"
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    process = context.Process(target=hold_partial_journal, args=(tmp_path, payload, ready))
    process.start()
    assert ready.wait(timeout=2)
    state = hub.validate_runtime(tmp_path, plan)
    process.join(timeout=2)
    assert process.exitcode == 0
    assert state["last_event_id"] == "test-partial-read"


def test_all_remaining_batches_have_short_parts_and_preserve_scope(plan):
    assert "short_parts" in plan["owner_decisions"]
    for batch in plan["batches"][2:]:
        parts = batch["sub_batches"]
        assert 3 <= len(parts) <= 6
        identifiers = [part.split(" ", 1)[0] for part in parts]
        assert len(identifiers) == len(set(identifiers))
        assert all(name.startswith(batch["id"]) for name in identifiers)
    assert len(plan["owner_decisions"]["deferred"]) == 4
    assert plan["capacity_acceptance"]["authenticated_active_users"] == 5000
    assert plan["capacity_acceptance"]["durable_jobs_min"] == 15000


@pytest.mark.parametrize("active_users", [1000, 4999])
def test_plan_cannot_lower_confirmed_5000_user_target(plan, active_users):
    plan["capacity_acceptance"]["authenticated_active_users"] = active_users
    with pytest.raises(ValueError, match="capacity acceptance weakened"):
        hub.validate_plan(plan)


@pytest.mark.parametrize("active_users", [5000, 6000])
def test_capacity_heading_uses_current_plan_and_preserves_open_acceptance(plan, tmp_path, active_users):
    plan["capacity_acceptance"]["authenticated_active_users"] = active_users
    plan["capacity_acceptance"]["durable_jobs_min"] = active_users * 3
    event = {
        "event_id": "test-fr09-open",
        "batch_id": "FR-09",
        "status": "in_progress",
        "summary_ar": "اختبار عرض فقط",
    }
    state = hub.render(tmp_path, plan, [event])
    report = (tmp_path / plan["report"]).read_text(encoding="utf-8")
    assert f"## عقد قبول {active_users} مستخدم متعدد المشاريع والمحادثات" in report
    assert state["batches"]["FR-09"]["status"] == "in_progress"
    assert state["release_status"] == "FINAL_RELEASE_IN_PROGRESS_NOT_RELEASED"
    assert plan["capacity_acceptance"]["status"] == "NOT_YET_ACCEPTED_5000_FULL_MIXED_PROFILE"
