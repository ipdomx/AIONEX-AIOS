#!/usr/bin/env python3
"""Fail-closed, side-effect-free FR-09 full mixed-load evidence gate.

A passed synthetic sharded-read test never substitutes for authenticated
multi-tenant project/conversation creation and durable-job workload acceptance.
No network, database, provider, key, or production access is used here.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

REQUIRED_FLAGS = (
    "authenticated_users_5000",
    "projects_15000",
    "conversations_15000",
    "durable_jobs_15000",
    "lost_jobs_zero",
    "duplicate_terminal_zero",
    "tenant_leaks_zero",
    "ordinary_read_p95_le_500ms",
    "durable_enqueue_p95_le_1000ms",
    "unexpected_error_rate_le_0_5pct",
    "steady_state_15m",
    "provider_spend_zero",
)
MIN_USERS = 5000
MIN_ASSETS = 15000
MIN_STEADY_SECONDS = 900
MIN_STEADY_ROUNDS = 30
MIN_STEADY_READS = 150000
MAX_READ_P95_MS = 500.0
MAX_ENQUEUE_P95_MS = 1000.0
MAX_ERROR_RATE = 0.005


def at(value: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def exact_integer(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def finite_number(value: Any, *, ceiling: float | None = None) -> bool:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return False
    return ceiling is None or value <= ceiling


def zero_integer(value: Any) -> bool:
    return exact_integer(value, 0)


def evaluate(mixed: Any, read_only: Any = None) -> dict[str, Any]:
    """Validate full 5000-user mixed acceptance from actual observations.

    The optional read-only receipt is an independent sub-test and cannot
    upgrade an absent or failed full-mixed receipt, even if perfectly green.
    """
    m = mixed if isinstance(mixed, dict) else {}
    flags = at(m, "checks")
    flags = flags if isinstance(flags, dict) else {}
    missing = [key for key in REQUIRED_FLAGS if key not in flags]
    unpassed = [key for key in REQUIRED_FLAGS if flags.get(key) is not True]
    observations = at(m, "http_observation_count")
    errors = at(m, "error_count")
    measured_rate = (
        errors / observations
        if integer(errors) and integer(observations, 1)
        else None
    )
    ramp = at(m, "ramp")
    ramp_steps = [at(step, "users") for step in ramp] if isinstance(ramp, list) else []

    measured = {
        "full_receipt_schema": exact_integer(at(m, "schema"), 1),
        "users": integer(at(m, "profile", "users"), MIN_USERS),
        "projects_profile": integer(at(m, "profile", "projects"), MIN_ASSETS),
        "conversations_profile": integer(at(m, "profile", "conversations"), MIN_ASSETS),
        "jobs_profile": integer(at(m, "profile", "jobs"), MIN_ASSETS),
        "ramp_reaches_5000": ramp_steps == [25, 100, 250, 500, 1000, 2500, 5000],
        "15m_profile": integer(at(m, "profile", "steady_seconds"), MIN_STEADY_SECONDS),
        "15m_measured_elapsed": finite_number(at(m, "completed_at_epoch"))
        and finite_number(at(m, "started_at_epoch"))
        and at(m, "completed_at_epoch") - at(m, "started_at_epoch") >= MIN_STEADY_SECONDS,
        "steady_rounds": integer(at(m, "steady_state", "rounds"), MIN_STEADY_ROUNDS),
        "steady_reads": integer(at(m, "steady_state", "requests"), MIN_STEADY_READS),
        "steady_read_p95": finite_number(at(m, "steady_state", "p95_ms"), ceiling=MAX_READ_P95_MS),
        "authenticated_read_p95": finite_number(at(m, "latency", "auth_read", "p95_ms"), ceiling=MAX_READ_P95_MS),
        "enqueue_p95": finite_number(at(m, "latency", "enqueue", "p95_ms"), ceiling=MAX_ENQUEUE_P95_MS),
        "project_creation_api_covered": integer(at(m, "latency", "project_create", "count"), MIN_ASSETS),
        "conversation_creation_api_covered": integer(at(m, "latency", "conversation_create", "count"), MIN_ASSETS),
        "fifteen_thousand_projects": integer(at(m, "db", "projects"), MIN_ASSETS),
        "fifteen_thousand_conversations": integer(at(m, "db", "threads"), MIN_ASSETS),
        "fifteen_thousand_completed_jobs": integer(at(m, "db", "jobs_completed"), MIN_ASSETS),
        "fifteen_thousand_total_jobs": integer(at(m, "db", "jobs_total"), MIN_ASSETS),
        "no_queued_jobs": zero_integer(at(m, "db", "jobs_queued")),
        "no_running_jobs": zero_integer(at(m, "db", "jobs_running")),
        "no_failed_jobs": zero_integer(at(m, "db", "jobs_failed")),
        "no_cancelled_jobs": zero_integer(at(m, "db", "jobs_cancelled")),
        "no_review_needed_jobs": zero_integer(at(m, "db", "jobs_needs_review")),
        "no_cross_tenant_mismatch": zero_integer(at(m, "db", "tenant_mismatch_jobs")),
        "cross_tenant_negatives_5000": integer(at(m, "cross_tenant_negative_pass"), MIN_USERS),
        "unique_job_ids": integer(at(m, "unique_job_ids"), MIN_ASSETS),
        "unexpected_error_rate": measured_rate is not None and measured_rate <= MAX_ERROR_RATE,
        "provider_external_calls_zero": zero_integer(at(m, "provider", "external_calls")),
        "provider_spend_zero": finite_number(at(m, "provider", "provider_spend_usd"), ceiling=0.0),
    }

    read = read_only if isinstance(read_only, dict) else {}
    read_result = at(read, "result")
    read_stage = (
        at(read, "status") == "PASS_5000_SHARDED_READ_15M_SLO"
        and integer(at(read, "profile", "users"), MIN_USERS)
        and integer(at(read, "profile", "requests"), MIN_STEADY_READS)
        and integer(at(read, "profile", "rounds"), MIN_STEADY_ROUNDS)
        and isinstance(read_result, dict)
        and zero_integer(read_result.get("errors"))
        and exact_integer(read_result.get("http_200"), at(read, "profile", "requests"))
        and finite_number(read_result.get("max_shard_p95_ms"), ceiling=MAX_READ_P95_MS)
    )
    failed_measured = [key for key, okay in measured.items() if not okay]
    accepted = (
        m.get("status") == "PASS"
        and not missing and not unpassed and not failed_measured
    )
    return {
        "schema": "aionex.fr09.full-mixed-evidence-verdict.v1",
        "status": "FULL_MIXED_ACCEPTED" if accepted else "HOLD_FULL_MIXED",
        "mixed_receipt_claim": m.get("status") if isinstance(m.get("status"), str) else "ABSENT",
        "missing_flag_names": missing,
        "unpassed_flag_names": unpassed,
        "failed_measured_conditions": failed_measured,
        "measured_error_rate": round(measured_rate, 7) if measured_rate is not None else None,
        "read_only_envelope_pass": read_stage,
        "read_only_envelope_cannot_override_mixed": True,
        "target_authenticated_users": MIN_USERS,
        "target_projects": MIN_ASSETS,
        "target_conversations": MIN_ASSETS,
        "target_durable_jobs": MIN_ASSETS,
        "heavy_ai_5000_simultaneous_inference_proven": False,
        "live_production_load_test_executed": False,
        "network_or_data_mutation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mixed", type=Path, help="full mixed workload JSON receipt")
    parser.add_argument("--read-only", type=Path, help="optional sharded read receipt")
    args = parser.parse_args()
    if args.mixed is None and args.read_only is None:
        parser.error("at least one evidence receipt is required")
    try:
        mixed = json.loads(args.mixed.read_text()) if args.mixed else None
        reads = json.loads(args.read_only.read_text()) if args.read_only else None
        report = evaluate(mixed, reads)
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"status": "INVALID_EVIDENCE", "error_type": type(exc).__name__}, sort_keys=True))
        return 3
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "FULL_MIXED_ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
