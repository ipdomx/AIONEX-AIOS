"""Roadmap regressions: merged source is not production or host-drain proof."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def admission():
    plan = json.loads((ROOT / "docs/project/PLAN.json").read_text())
    return next(batch for batch in plan["batches"] if batch["id"] == "FR-06")[
        "host_state_cutover_admission"
    ]


def test_current_part_includes_merged_runtime_and_registry():
    state = admission()
    runtime = state["security_scan_runtime_source"]
    assert state["source_part"] == "FR-06C5D9B2B2"
    assert runtime["source_part"] == "FR-06C5D7B8"
    assert state["migration"] == "20260920_0063"
    assert runtime["migration"] == "20260918_0053"
    assert runtime["authority_schema_version"] == 6
    assert runtime["registry_pr"] == 720
    assert runtime["runtime_pr"] == 722
    assert runtime["source_implementation_present"] is True
    migration = ROOT / "web-dashboard/backend/alembic/versions/20260918_0053_scan_execution_ownership.py"
    assert migration.is_file()


@pytest.mark.parametrize("name", [
    "security_scan_worker.py", "security_scan_resources.py",
    "security_scan_process_entry.py", "security_scan_zap_resources.py",
])
def test_runtime_evidence_has_tracked_implementation(name):
    assert (ROOT / "web-dashboard/backend/app/services" / name).is_file()


@pytest.mark.parametrize("key", [
    "production_zap_exclusivity_verified", "production_deployment_verified",
    "production_database_migrated", "coverage_verified", "full_host_closure",
    "full_d7_completed", "legacy_or_ambiguous_work_automatically_settled",
])
def test_source_contract_does_not_close_production_or_parent(key):
    state = admission()
    assert state["security_scan_runtime_source"][key] is False
    assert state["full_host_admission_closed"] is False


@pytest.mark.parametrize("key", [
    "security_scan_request_admission_source",
    "security_scan_zap_observation_source",
    "security_scan_no_replay_source",
])
def test_historical_parts_explicitly_point_to_current_runtime(key):
    part = admission()[key]
    assert part["historical_part_scope"] is True
    assert part["current_runtime_contract"] == "security_scan_runtime_source"


def test_runtime_preserves_unresolved_work_and_cancellation_boundary():
    runtime = admission()["security_scan_runtime_source"]
    assert runtime["cancellation_is_intent_not_cleanup_proof"] is True
    assert runtime["ambiguous_zap_keeps_fence"] is True
    assert runtime["automatic_stale_takeover"] is False
    assert runtime["automatic_uncertain_requeue"] is False


def test_postmerge_acceptance_remains_in_live_journal():
    runtime = admission()["security_scan_runtime_source"]
    assert runtime["postmerge_acceptance_source"] == "docs/project/runtime/events.jsonl"
    assert "main_checks_passed" not in runtime
    assert "server_source_synchronized" not in runtime
    for evidence in runtime["evidence"]:
        assert (ROOT / evidence).is_file()


def test_remaining_scope_keeps_real_operational_requirements():
    remaining = "\n".join(admission()["remaining_before_host_cutover_ar"])
    for required in ("ZAP", "realtime", "LiveKit", "C5D", "القديمة", "استعادة"):
        assert required in remaining
    assert "استكمال سجل ملكية تنفيذ الفحص الدائم" not in remaining
