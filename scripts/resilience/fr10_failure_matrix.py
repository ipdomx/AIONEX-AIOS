"""Synthetic FR-10 fault-tolerance acceptance harness.

This module is deliberately provider-free and database-free. It models only the
acceptance semantics owned by FR-10: ambiguous outcomes must not be replayed
after an external-effect boundary, stale fencing generations must not complete,
fairness metrics must be resource-class aware, and resource aborts must fail
closed.

It is not a production scheduler and it does not modify shared runtime code.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RETRY_SAFE = "retry_safe"
RECONCILE_NO_REPLAY = "reconcile_no_replay"
TERMINAL = "terminal"
ACCEPT = "accept"
REJECT_STALE = "reject_stale"


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    failure_kind: str
    effect_started: bool
    db_commit_state: str
    provider_outcome: str
    attempt_fencing_token: int
    current_fencing_token: int
    attempts: int
    max_attempts: int
    resource_abort: bool = False
    expected_action: str | None = None


def _retry_budget_left(scenario: Scenario) -> bool:
    return scenario.attempts < scenario.max_attempts


def decide_action(scenario: Scenario) -> str:
    """Return the only safe synthetic disposition for one failure scenario."""
    if scenario.attempt_fencing_token != scenario.current_fencing_token:
        return REJECT_STALE

    if scenario.provider_outcome == "confirmed_success":
        return ACCEPT

    ambiguous = (
        scenario.db_commit_state == "unknown"
        or scenario.provider_outcome == "uncertain"
        or (scenario.resource_abort and scenario.effect_started)
    )
    if ambiguous and scenario.effect_started:
        return RECONCILE_NO_REPLAY

    if scenario.effect_started:
        # Once an external side effect may have happened, FR-10 does not allow
        # blind automatic replay merely because the failure is transient.
        return RECONCILE_NO_REPLAY

    if not _retry_budget_left(scenario):
        return TERMINAL

    if scenario.db_commit_state in {"not_committed", "not_started"}:
        return RETRY_SAFE

    if scenario.provider_outcome in {"not_started", "confirmed_failure"}:
        return RETRY_SAFE

    return TERMINAL


def load_fixture(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def scenario_from_dict(payload: dict[str, Any]) -> Scenario:
    return Scenario(
        scenario_id=str(payload["id"]),
        failure_kind=str(payload["failure_kind"]),
        effect_started=bool(payload["effect_started"]),
        db_commit_state=str(payload["db_commit_state"]),
        provider_outcome=str(payload["provider_outcome"]),
        attempt_fencing_token=int(payload["attempt_fencing_token"]),
        current_fencing_token=int(payload["current_fencing_token"]),
        attempts=int(payload["attempts"]),
        max_attempts=int(payload["max_attempts"]),
        resource_abort=bool(payload.get("resource_abort", False)),
        expected_action=(
            str(payload["expected_action"])
            if payload.get("expected_action") is not None
            else None
        ),
    )


def evaluate_matrix(payload: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    automatic_replays_after_effect = 0
    duplicate_send_risk = 0
    duplicate_charge_risk = 0
    stale_completions_accepted = 0

    for raw in payload["scenarios"]:
        scenario = scenario_from_dict(raw)
        action = decide_action(scenario)
        if scenario.effect_started and action == RETRY_SAFE:
            automatic_replays_after_effect += 1
            duplicate_send_risk += 1
            duplicate_charge_risk += 1
        if (
            scenario.attempt_fencing_token != scenario.current_fencing_token
            and action == ACCEPT
        ):
            stale_completions_accepted += 1
        rows.append(
            {
                "id": scenario.scenario_id,
                "failure_kind": scenario.failure_kind,
                "action": action,
                "matches_expected": (
                    scenario.expected_action is None
                    or scenario.expected_action == action
                ),
            }
        )

    return {
        "rows": rows,
        "automatic_replays_after_effect": automatic_replays_after_effect,
        "duplicate_send_risk": duplicate_send_risk,
        "duplicate_charge_risk": duplicate_charge_risk,
        "stale_completions_accepted": stale_completions_accepted,
        "all_expected_actions_match": all(row["matches_expected"] for row in rows),
    }


def fairness_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    entries = list(payload["fairness_queue"])
    eligible = set(payload["eligible_resource_classes"])
    by_class: dict[str, dict[str, Any]] = {}
    for row in entries:
        resource_class = str(row["resource_class"])
        wait = float(row["wait_seconds"])
        tenant = str(row["tenant"])
        item = by_class.setdefault(
            resource_class,
            {"queued": 0, "oldest_wait_seconds": 0.0, "tenants": set()},
        )
        item["queued"] += 1
        item["oldest_wait_seconds"] = max(item["oldest_wait_seconds"], wait)
        item["tenants"].add(tenant)

    rendered: dict[str, Any] = {}
    for resource_class, item in sorted(by_class.items()):
        rendered[resource_class] = {
            "queued": int(item["queued"]),
            "oldest_wait_seconds": round(float(item["oldest_wait_seconds"]), 3),
            "tenant_count": len(item["tenants"]),
            "worker_eligible": resource_class in eligible,
            "classification": (
                "bounded_fairness_candidate"
                if resource_class in eligible
                else "capacity_or_configuration_gap"
            ),
        }
    return {"by_resource_class": rendered}


def _nearest_rank(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[min(rank - 1, len(ordered) - 1)]


def collate_metrics(payload: dict[str, Any]) -> dict[str, float]:
    sample = payload["metrics_sample"]
    window_seconds = float(sample["window_seconds"])
    completed_jobs = int(sample["completed_jobs"])
    active_slots = int(sample["worker_active_slots"])
    capacity = int(sample["worker_capacity"])
    recovery = [float(v) for v in sample["recovery_seconds"]]
    waits = [float(v) for v in sample["queue_wait_seconds"]]
    return {
        "recovery_max_seconds": round(max(recovery, default=0.0), 3),
        "recovery_p95_seconds": round(_nearest_rank(recovery, 0.95), 3),
        "queue_wait_p95_seconds": round(_nearest_rank(waits, 0.95), 3),
        "throughput_jobs_per_minute": round(
            (completed_jobs / window_seconds) * 60.0 if window_seconds else 0.0,
            3,
        ),
        "worker_saturation": round(
            active_slots / capacity if capacity else 0.0,
            4,
        ),
    }


def run_acceptance(payload: dict[str, Any]) -> dict[str, Any]:
    matrix = evaluate_matrix(payload)
    fairness = fairness_metrics(payload)
    metrics = collate_metrics(payload)
    return {
        "matrix": matrix,
        "fairness": fairness,
        "metrics": metrics,
        "accepted": bool(
            matrix["all_expected_actions_match"]
            and matrix["automatic_replays_after_effect"] == 0
            and matrix["duplicate_send_risk"] == 0
            and matrix["duplicate_charge_risk"] == 0
            and matrix["stale_completions_accepted"] == 0
        ),
        "heavy_or_live_effects": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    args = parser.parse_args()
    result = run_acceptance(load_fixture(args.fixture))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
