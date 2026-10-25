"""Read-only FR09 15-minute synthetic HTTP evidence verifier.

This checks only a bounded authenticated read sub-gate. It NEVER authorizes
the full release, synthetic-job/model-equivalence, 72h stability, or deployment.
No network, files outside the supplied receipt, credentials, or customer data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

ROUTES = ("identity", "projects", "conversations")
MIN_USERS = 5000
MIN_TENANTS = 100
MIN_JOBS_PER_USER = 3
MIN_MINUTES = 15
MIN_READS_PER_MINUTE = MIN_USERS * len(ROUTES)
P95_MS_MAX = 500.0


class ReadEvidenceError(ValueError):
    """Machine-checkable reason a read-only capacity slice cannot pass."""


def _strict_int(value: Any, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ReadEvidenceError(f"{name} must be an integer >= {minimum}")
    return value


def _millis(value: Any, name: str) -> float:
    if type(value) not in (int, float):
        raise ReadEvidenceError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ReadEvidenceError(f"{name} must be finite and nonnegative")
    return result


def _is_true(value: Any, name: str) -> None:
    if value is not True:
        raise ReadEvidenceError(f"{name} must be true")


def verify_sustained_read_slice(
    payload: dict[str, Any], *, driver_source: Path | None = None,
) -> dict[str, Any]:
    """Validate actual 15-minute *paced* HTTP evidence, not final FR09 GO."""
    if type(payload) is not dict:
        raise ReadEvidenceError("receipt must be a JSON object")

    for key in (
        "test_passed",
        "original_live_production_container_identities_unchanged",
        "synthetic_bearer_tokens_destroyed",
        "sustained_15min_synthetic_reads_proved",
    ):
        _is_true(payload.get(key), key)

    if payload.get("production_changed") is not False:
        raise ReadEvidenceError("production_changed must be false")
    if payload.get("full_5000_sustained_capacity_accepted") is not False:
        raise ReadEvidenceError("full-release acceptance must remain false")

    if _strict_int(payload.get("lab_containers_remaining"), "lab_containers_remaining", 0) != 0:
        raise ReadEvidenceError("lab containers must be absent")
    users = _strict_int(payload.get("synthetic_cohort_size"), "cohort_size", MIN_USERS)
    organizations = _strict_int(payload.get("synthetic_tenant_rows"), "tenants", MIN_TENANTS)
    for key in ("synthetic_project_rows", "synthetic_task_rows", "synthetic_conversation_rows"):
        _strict_int(payload.get(key), key, users * MIN_JOBS_PER_USER)

    minutes = _strict_int(payload.get("steady_state_minutes"), "steady_state_minutes", MIN_MINUTES)
    if minutes != MIN_MINUTES:
        raise ReadEvidenceError("this 15-minute gate requires exactly 15 recorded windows")

    records = payload.get("per_minute_read_metrics")
    if type(records) is not list or len(records) != MIN_MINUTES:
        raise ReadEvidenceError("must retain all 15 per-minute source records")

    full_stage = payload.get("measurements")
    if type(full_stage) is not list or len(full_stage) != 1:
        raise ReadEvidenceError("must retain one complete multi-tenant stage")
    actual_route_records = full_stage[0].get("measurement")
    if type(actual_route_records) is not list or len(actual_route_records) != len(ROUTES):
        raise ReadEvidenceError("the three HTTP route aggregates are mandatory")

    total_completed = 0
    minutes_validated: list[dict[str, Any]] = []
    observed_window_ends: list[datetime] = []
    for i, minute in enumerate(records, 1):
        if type(minute) is not dict:
            raise ReadEvidenceError(f"minute {i} is not an object")
        if _strict_int(minute.get("minute"), f"minute[{i}].index", 1) != i:
            raise ReadEvidenceError("missing, repeated, or reordered minute")
        expected = _strict_int(minute.get("total_expected"), f"minute[{i}].offered", MIN_READS_PER_MINUTE)
        if expected != users * len(ROUTES):
            raise ReadEvidenceError("wrong per-minute offered request count")
        completed = _strict_int(minute.get("completed_http_200"), f"minute[{i}].http200", 0)
        if completed != expected:
            raise ReadEvidenceError(f"minute {i} has an invalid response or error")
        latency = minute.get("route_p95_ms")
        if type(latency) is not dict or set(latency) != set(ROUTES):
            raise ReadEvidenceError(f"minute {i} has missing/unexpected route P95 fields")
        values = {route: _millis(latency[route], f"minute[{i}].{route}") for route in ROUTES}
        if any(value > P95_MS_MAX for value in values.values()):
            raise ReadEvidenceError(f"minute {i} exceeded ordinary-read P95")
        lateness = _millis(minute.get("minute_end_lateness_ms"), "minute_end_lateness_ms")
        if lateness > 2000:
            raise ReadEvidenceError(f"minute {i} has >2 second generator backlog")
        timestamp = minute.get("started_at_utc")
        if not isinstance(timestamp, str):
            raise ReadEvidenceError(f"minute {i} timestamp missing")
        try:
            instant = datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise ReadEvidenceError(f"minute {i} timestamp invalid") from exc
        if instant.tzinfo is None:
            raise ReadEvidenceError(f"minute {i} timezone missing")
        observed_window_ends.append(instant)
        total_completed += completed
        minutes_validated.append({"minute": i, "http200": completed, "p95_ms": values})

    aggregates: dict[str, float] = {}
    for record in actual_route_records:
        if type(record) is not dict:
            raise ReadEvidenceError("route aggregate must be object")
        name = record.get("path")
        if name not in ROUTES or name in aggregates:
            raise ReadEvidenceError("unknown/duplicate route aggregate")
        expected_requests = users * MIN_MINUTES
        if _strict_int(record.get("requests"), f"{name}.requests", expected_requests) != expected_requests:
            raise ReadEvidenceError("route did not receive each user once per minute")
        if _strict_int(record.get("success_200"), f"{name}.http200", expected_requests) != expected_requests:
            raise ReadEvidenceError("route has non-200/invalid payload")
        p95 = _millis(record.get("p95_ms"), f"{name}.p95")
        if p95 > P95_MS_MAX:
            raise ReadEvidenceError(f"{name} aggregate P95 exceeds 500ms")
        aggregates[name] = p95
    if set(aggregates) != set(ROUTES):
        raise ReadEvidenceError("missing route aggregate")
    if total_completed != MIN_READS_PER_MINUTE * MIN_MINUTES:
        raise ReadEvidenceError("window and route totals disagree")

    for i, (earlier, later) in enumerate(
        pairwise(observed_window_ends), 2
    ):
        step_seconds = (later - earlier).total_seconds()
        if not 55 <= step_seconds <= 65:
            raise ReadEvidenceError(f"minutes {i-1} and {i} are not spaced one minute")
    between_window_ends = (
        observed_window_ends[-1] - observed_window_ends[0]
    ).total_seconds()
    if not 838 <= between_window_ends <= 900:
        raise ReadEvidenceError("timestamp span does not establish 14 minutes between ends")

    elapsed = payload.get("steady_state_elapsed_seconds")
    evidence_mode = "direct_client_elapsed_value"
    driver_sha256 = None
    if elapsed is None:
        # The original 2026-10-25 runner asserted the unpersisted client
        # elapsed>=900s before emitting test_passed=true. Replaying the
        # pinned source makes this an *attested* proof, not directly recorded
        # duration. Never imply the clock value itself was retained.
        if driver_source is None:
            raise ReadEvidenceError("missing direct elapsed time and driver attestation")
        driver_bytes = driver_source.read_bytes()
        if len(driver_bytes) > 100_000:
            raise ReadEvidenceError("source driver exceeds bounded length")
        driver_text = driver_bytes.decode("utf-8")
        required = (
            'assert observed["steady_state_elapsed_seconds"] >= 900',
            'assert observed["steady_state_minutes"] == 15',
            'result["sustained_15min_synthetic_reads_proved"]=True',
        )
        if any(fragment not in driver_text for fragment in required):
            raise ReadEvidenceError("driver does not attest 900-second source gate")
        driver_sha256 = hashlib.sha256(driver_bytes).hexdigest()
        duration = None
        evidence_mode = "source_attested_minimum_900s_not_directly_persisted"
    else:
        duration = _millis(elapsed, "steady_state_elapsed_seconds")
        if duration < MIN_MINUTES * 60 or duration > (MIN_MINUTES + 1) * 60:
            raise ReadEvidenceError("elapsed time inconsistent with 15-minute steady state")

    offered = _millis(payload.get("offered_requests_per_second"), "offered_requests_per_second")
    if not 249 <= offered <= 251:
        raise ReadEvidenceError("observed input rate does not match 250 HTTP requests/s")

    return {
        "schema": "aionex.fr09.sustained-paced-read-slice-verified.v1",
        "read_slice_verified": True,
        "synthetic_authenticated_users": users,
        "distinct_synthetic_tenants": organizations,
        "steady_state_minutes": MIN_MINUTES,
        "observed_duration_s": duration,
        "elapsed_evidence_mode": evidence_mode,
        "source_driver_sha256": driver_sha256,
        "minute_ends_span_seconds": round(between_window_ends, 3),
        "http200_total": total_completed,
        "ordinary_read_p95_ms": aggregates,
        "per_minute_p95_all_routes_pass": True,
        "full_5000_simultaneous_requests_accepted": False,
        "actual_15000_model_inferences_proven": False,
        "durable_enqueue_p95_accepted": False,
        "natural_72h_accepted": False,
        "final_release_accepted": False,
        "release_decision": "HOLD",
        "safety_note": "This is a 5,000-user paced read slice only, not a full AIOS release gate.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--driver", type=Path)
    args = parser.parse_args()
    raw = args.receipt.read_bytes()
    if len(raw) > 10_000_000:
        raise ReadEvidenceError("evidence larger than supported 10 MB")
    data = json.loads(raw)
    verified = verify_sustained_read_slice(data, driver_source=args.driver)
    verified["source_sha256"] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(verified, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
