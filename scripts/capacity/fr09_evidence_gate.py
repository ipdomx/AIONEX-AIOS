#!/usr/bin/env python3
"""Fail-closed, side-effect-free FR-09 full mixed-load evidence gate.

A passed synthetic sharded-read test never substitutes for authenticated
multi-tenant project/conversation creation and durable-job workload acceptance.
No network, database, provider, or production access is used here. An optional
local 0600 trusted telemetry-key file is read only for source authentication.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import stat
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
MAX_SERVER_SAMPLE_GAP_SECONDS = 30.0
MIN_SERVER_SAMPLE_COUNT = 31
# Any JSON integer exceeding IEEE-754's safe range can silently lose
# identity/metric precision in browser, JS and dashboard report processing.
MAX_SAFE_JSON_INTEGER = (1 << 53) - 1


def at(value: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def integer(value: Any, minimum: int = 0) -> bool:
    return (
        type(value) is int and minimum <= value <= MAX_SAFE_JSON_INTEGER
    )


def exact_integer(value: Any, expected: int) -> bool:
    return type(value) is int and value == expected


def finite_number(value: Any, *, ceiling: float | None = None) -> bool:
    if type(value) not in (int, float):
        return False
    # Check the bound before math.isfinite: converting a very large Python
    # integer to float otherwise raises OverflowError on untrusted JSON.
    if value < 0 or value > MAX_SAFE_JSON_INTEGER:
        return False
    return math.isfinite(value) and (ceiling is None or value <= ceiling)


def zero_integer(value: Any) -> bool:
    return exact_integer(value, 0)



def sampled_authenticated_concurrency(
    steady: Any, *, trusted_key: bytes | None = None
) -> tuple[bool, int | None]:
    """Require 5,000 server-measured concurrent authenticated users throughout 15m.

    This is a strict *receipt structure* admission, not an origin attestation.
    The sample stream must carry a SHA256 HMAC from an independently trusted
    server instrumentation key. This verifies the *source key*, not whether
    the instrumented sessions themselves were authentic; that needs separate
    end-to-end evidence and secure key provenance.
    """
    if not isinstance(steady, dict):
        return False, None
    window_start = steady.get("window_start_epoch")
    window_end = steady.get("window_end_epoch")
    raw = steady.get("server_concurrency")
    if (
        not finite_number(window_start)
        or not finite_number(window_end)
        or window_end - window_start < MIN_STEADY_SECONDS
        or not isinstance(raw, dict)
        or raw.get("source") != "server-authenticated-session-tracker-v1"
        or not isinstance(raw.get("samples"), list)
    ):
        return False, None

    samples = raw["samples"]
    if len(samples) < MIN_SERVER_SAMPLE_COUNT or len(samples) > 3600:
        return False, None

    previous: float | None = None
    minimum: int | None = None
    for row in samples:
        if not isinstance(row, dict):
            return False, None
        observed = row.get("at_epoch")
        sessions = row.get("authenticated_sessions")
        users = row.get("distinct_authenticated_users")
        if (
            not finite_number(observed)
            or not integer(sessions, MIN_USERS)
            or not integer(users, MIN_USERS)
            or users > sessions
        ):
            return False, None
        if previous is None:
            if abs(observed - window_start) > 1.0:
                return False, None
        elif not (previous < observed <= previous + MAX_SERVER_SAMPLE_GAP_SECONDS + 0.001):
            return False, None
        if observed < window_start or observed > window_end:
            return False, None
        previous = observed
        minimum = users if minimum is None else min(minimum, users)

    if previous is None or abs(previous - window_end) > 1.0:
        return False, None
    if type(trusted_key) is not bytes or len(trusted_key) < 32:
        return False, None
    claimed_hmac = raw.get("hmac_sha256")
    if not isinstance(claimed_hmac, str) or len(claimed_hmac) != 64:
        return False, None
    try:
        expected_hmac = hmac.new(
            trusted_key,
            json.dumps(
                {
                    "window_start_epoch": window_start,
                    "window_end_epoch": window_end,
                    "source": raw["source"],
                    "samples": samples,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    except (TypeError, ValueError, OverflowError):
        return False, None
    if not hmac.compare_digest(expected_hmac, claimed_hmac):
        return False, None
    unique_active = steady.get("unique_authenticated_users")
    if not integer(unique_active, MIN_USERS) or minimum is None or minimum > unique_active:
        return False, None
    return True, minimum


def evaluate(
    mixed: Any, read_only: Any = None, *, trusted_server_gauge_key: bytes | None = None
) -> dict[str, Any]:
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

    # These are distinct HTTP route families. One reported request cannot
    # simultaneously be a steady authenticated read, project create, and
    # conversation create. Prevent internally contradictory "PASS" receipts.
    steady_reads = at(m, "steady_state", "requests")
    steady_errors = at(m, "steady_state", "errors")
    project_creates = at(m, "latency", "project_create", "count")
    conversation_creates = at(m, "latency", "conversation_create", "count")
    request_accounting = (
        integer(observations, 1)
        and integer(steady_reads)
        and integer(project_creates)
        and integer(conversation_creates)
        and observations >= steady_reads + project_creates + conversation_creates
    )
    steady_error_accounting = (
        integer(steady_errors) and integer(errors) and integer(steady_reads)
        and integer(observations, 1)
        and steady_errors <= errors <= observations
        and steady_errors <= steady_reads
    )
    # Profile fields are targets, never substitutes for actual observed
    # authenticated concurrency or an independently timestamped steady window.
    start, end = at(m, "started_at_epoch"), at(m, "completed_at_epoch")
    steady_start = at(m, "steady_state", "window_start_epoch")
    steady_end = at(m, "steady_state", "window_end_epoch")
    genuine_steady_window = (
        all(finite_number(value) for value in (start, end, steady_start, steady_end))
        and start <= steady_start < steady_end <= end
        and steady_end - steady_start >= MIN_STEADY_SECONDS
    )
    minimum_active = at(m, "steady_state", "authenticated_active_users_min")
    unique_active = at(m, "steady_state", "unique_authenticated_users")
    authenticated_population_consistent = (
        integer(minimum_active, MIN_USERS)
        and integer(unique_active, MIN_USERS)
        and minimum_active <= unique_active
    )
    server_series_valid, server_minimum = sampled_authenticated_concurrency(
        at(m, "steady_state"), trusted_key=trusted_server_gauge_key
    )
    jobs_total = at(m, "db", "jobs_total")
    terminal_and_pending = [
        at(m, "db", field) for field in (
            "jobs_completed", "jobs_queued", "jobs_running", "jobs_failed",
            "jobs_cancelled", "jobs_needs_review",
        )
    ]
    job_accounting = (
        integer(jobs_total)
        and all(integer(value) for value in terminal_and_pending)
        and jobs_total == sum(terminal_and_pending)
    )
    unique_id_accounting = (
        integer(jobs_total)
        and exact_integer(at(m, "unique_job_ids"), jobs_total)
    )
    actual_assets_meet_profile = (
        all(
            integer(profile) and integer(actual) and actual >= profile
            for profile, actual in (
                (at(m, "profile", "projects"), at(m, "db", "projects")),
                (at(m, "profile", "conversations"), at(m, "db", "threads")),
                (at(m, "profile", "jobs"), jobs_total),
            )
        )
    )

    measured = {
        "full_receipt_schema": exact_integer(at(m, "schema"), 1),
        "users": integer(at(m, "profile", "users"), MIN_USERS),
        "projects_profile": integer(at(m, "profile", "projects"), MIN_ASSETS),
        "conversations_profile": integer(at(m, "profile", "conversations"), MIN_ASSETS),
        "jobs_profile": integer(at(m, "profile", "jobs"), MIN_ASSETS),
        "ramp_reaches_5000": ramp_steps == [25, 100, 250, 500, 1000, 2500, 5000],
        "steady_authenticated_concurrency_measured": authenticated_population_consistent,
        "server_observed_5000_simultaneous_sessions_15m": server_series_valid,
        "15m_measured_steady_window": genuine_steady_window,
        "consistent_total_request_observations": request_accounting,
        "consistent_steady_errors": steady_error_accounting,
        "all_jobs_accounted_for": job_accounting,
        "unique_job_ids_match_total": unique_id_accounting,
        "actual_assets_meet_profile": actual_assets_meet_profile,
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
        "server_sample_minimum_distinct_users": server_minimum if server_series_valid else None,
        "server_series_hmac_verified": server_series_valid,
        "server_identity_and_capture_independently_audited": False,
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


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous evidence fields at every JSON object nesting depth."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _load(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle, object_pairs_hook=_reject_duplicate_json_keys)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mixed", type=Path, help="full mixed workload JSON receipt")
    parser.add_argument("--read-only", type=Path, help="optional sharded read receipt")
    parser.add_argument(
        "--trusted-server-gauge-key-file",
        type=Path,
        help="private key file (owner mode 0600) provisioned independently of load generator",
    )
    args = parser.parse_args()
    if args.mixed is None and args.read_only is None:
        parser.error("at least one evidence receipt is required")
    try:
        mixed = _load(args.mixed) if args.mixed else None
        reads = _load(args.read_only) if args.read_only else None
        key = None
        if args.trusted_server_gauge_key_file is not None:
            target = args.trusted_server_gauge_key_file
            if target.is_symlink():
                raise ValueError("trusted server gauge key may not be a symlink")
            metadata = target.stat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_uid != os.geteuid()
                or not 32 <= metadata.st_size <= 4096
            ):
                raise ValueError("trusted server gauge key must be private and size bounded")
            key = target.read_bytes()
        report = evaluate(mixed, reads, trusted_server_gauge_key=key)
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"status": "INVALID_EVIDENCE", "error_type": type(exc).__name__}, sort_keys=True))
        return 3
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "FULL_MIXED_ACCEPTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
