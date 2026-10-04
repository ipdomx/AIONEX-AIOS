from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "resilience" / "fr10_failure_matrix.py"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "fr10" / "failure_scenarios.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("fr10_failure_matrix", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_declared_failure_matrix_matches_safe_dispositions() -> None:
    module = _load_module()
    result = module.evaluate_matrix(_fixture())
    assert result["all_expected_actions_match"] is True
    assert result["automatic_replays_after_effect"] == 0
    assert result["duplicate_send_risk"] == 0
    assert result["duplicate_charge_risk"] == 0
    assert result["stale_completions_accepted"] == 0


def test_ambiguous_commit_and_provider_ack_never_auto_replay_after_effect() -> None:
    module = _load_module()
    rows = {
        row["id"]: row
        for row in module.evaluate_matrix(_fixture())["rows"]
    }
    assert rows["db-commit-ack-lost-after-effect"]["action"] == "reconcile_no_replay"
    assert rows["provider-ack-loss-after-send"]["action"] == "reconcile_no_replay"
    assert rows["memory-abort-after-effect"]["action"] == "reconcile_no_replay"


def test_pre_effect_failures_can_retry_only_with_budget() -> None:
    module = _load_module()
    rows = {
        row["id"]: row
        for row in module.evaluate_matrix(_fixture())["rows"]
    }
    assert rows["worker-loss-before-effect"]["action"] == "retry_safe"
    assert rows["network-loss-before-provider-send"]["action"] == "retry_safe"
    assert rows["db-failure-before-effect"]["action"] == "retry_safe"
    assert rows["memory-abort-before-effect"]["action"] == "retry_safe"
    assert rows["retry-budget-exhausted-before-effect"]["action"] == "terminal"


def test_stale_fencing_generation_is_rejected() -> None:
    module = _load_module()
    rows = {
        row["id"]: row
        for row in module.evaluate_matrix(_fixture())["rows"]
    }
    assert rows["stale-worker-completion-after-reclaim"]["action"] == "reject_stale"


def test_fairness_metrics_are_resource_class_aware() -> None:
    module = _load_module()
    metrics = module.fairness_metrics(_fixture())["by_resource_class"]
    assert metrics["cpu"] == {
        "queued": 3,
        "oldest_wait_seconds": 12.0,
        "tenant_count": 2,
        "worker_eligible": True,
        "classification": "bounded_fairness_candidate",
    }
    assert metrics["gpu"]["oldest_wait_seconds"] == 20.0
    assert metrics["gpu"]["classification"] == "bounded_fairness_candidate"
    assert metrics["tpu"]["oldest_wait_seconds"] == 30.0
    assert metrics["tpu"]["worker_eligible"] is False
    assert metrics["tpu"]["classification"] == "capacity_or_configuration_gap"


def test_metric_collation_is_deterministic_and_bounded() -> None:
    module = _load_module()
    metrics = module.collate_metrics(_fixture())
    assert metrics == {
        "recovery_max_seconds": 8.2,
        "recovery_p95_seconds": 8.2,
        "queue_wait_p95_seconds": 4.0,
        "throughput_jobs_per_minute": 24.0,
        "worker_saturation": 0.75,
    }


def test_end_to_end_synthetic_acceptance_has_no_live_effects() -> None:
    module = _load_module()
    result = module.run_acceptance(_fixture())
    assert result["accepted"] is True
    assert result["heavy_or_live_effects"] is False
