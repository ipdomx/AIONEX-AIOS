from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capacity" / "fr09_evidence_gate.py"
spec = importlib.util.spec_from_file_location("fr09_evidence_gate", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def mixed_pass():
    return {
        "schema": 1, "status": "PASS",
        "started_at_epoch": 1000.0, "completed_at_epoch": 1920.0,
        "profile": {"users": 5000, "projects": 15000, "conversations": 15000, "jobs": 15000,
                    "steady_seconds": 900},
        "ramp": [{"users": n} for n in (25, 100, 250, 500, 1000, 2500, 5000)],
        "checks": {key: True for key in module.REQUIRED_FLAGS},
        "db": {"projects": 15000, "threads": 15000, "jobs_total": 15000,
               "jobs_completed": 15000, "jobs_queued": 0, "jobs_running": 0,
               "jobs_failed": 0, "jobs_cancelled": 0, "jobs_needs_review": 0,
               "tenant_mismatch_jobs": 0},
        "steady_state": {
            "rounds": 30, "requests": 150000, "p95_ms": 27.3, "errors": 0,
            "window_start_epoch": 1010.0, "window_end_epoch": 1910.0,
            "authenticated_active_users_min": 5000,
            "unique_authenticated_users": 5000,
        },
        "latency": {"auth_read": {"p95_ms": 70}, "enqueue": {"p95_ms": 110},
                    "project_create": {"count": 15000},
                    "conversation_create": {"count": 15000}},
        "cross_tenant_negative_pass": 5000, "unique_job_ids": 15000,
        "http_observation_count": 185000, "error_count": 0,
        "provider": {"external_calls": 0, "provider_spend_usd": 0.0},
    }


def read_pass():
    return {
        "status": "PASS_5000_SHARDED_READ_15M_SLO",
        "profile": {"users": 5000, "requests": 150000, "rounds": 30},
        "result": {"http_200": 150000, "errors": 0, "max_shard_p95_ms": 17.135},
    }


def test_full_mixed_synthetic_fixture_can_pass():
    result = module.evaluate(mixed_pass(), read_pass())
    assert result["status"] == "FULL_MIXED_ACCEPTED"
    assert result["read_only_envelope_pass"]
    assert not result["failed_measured_conditions"]


def test_read_only_pass_never_substitutes_missing_full_receipt():
    result = module.evaluate(None, read_pass())
    assert result["status"] == "HOLD_FULL_MIXED"
    assert result["read_only_envelope_pass"]


def test_failed_full_receipt_not_overridden_by_green_read_only():
    d = mixed_pass(); d["status"] = "FAIL"
    result = module.evaluate(d, read_pass())
    assert result["status"] == "HOLD_FULL_MIXED"
    assert result["read_only_envelope_pass"]


def test_spoofed_green_flags_do_not_override_bad_latency():
    d = mixed_pass(); d["latency"]["auth_read"]["p95_ms"] = 2759.047
    result = module.evaluate(d, read_pass())
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "authenticated_read_p95" in result["failed_measured_conditions"]


def test_spoofed_green_flags_do_not_override_bad_error_rate():
    d = mixed_pass(); d["error_count"] = 21896
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "unexpected_error_rate" in result["failed_measured_conditions"]


def test_untested_create_project_and_conversation_routes_cannot_pass():
    d = mixed_pass(); d["latency"]["project_create"]["count"] = 0
    d["latency"]["conversation_create"]["count"] = 0
    r = module.evaluate(d)
    assert r["status"] == "HOLD_FULL_MIXED"
    assert "project_creation_api_covered" in r["failed_measured_conditions"]
    assert "conversation_creation_api_covered" in r["failed_measured_conditions"]


def test_tenant_leak_fails_closed_even_when_reported_pass():
    d = mixed_pass(); d["db"]["tenant_mismatch_jobs"] = 1
    assert module.evaluate(d)["status"] == "HOLD_FULL_MIXED"


def test_provider_spend_and_external_calls_fail_closed():
    d = mixed_pass(); d["provider"]["external_calls"] = 1
    assert module.evaluate(d)["status"] == "HOLD_FULL_MIXED"
    d = mixed_pass(); d["provider"]["provider_spend_usd"] = 0.01
    assert module.evaluate(d)["status"] == "HOLD_FULL_MIXED"


def test_boolean_or_string_flags_do_not_count_as_true():
    d = mixed_pass(); d["checks"]["tenant_leaks_zero"] = 1
    assert "tenant_leaks_zero" in module.evaluate(d)["unpassed_flag_names"]
    d = mixed_pass(); d["checks"]["tenant_leaks_zero"] = "true"
    assert module.evaluate(d)["status"] == "HOLD_FULL_MIXED"


def test_missing_actual_observations_cannot_pass():
    d = mixed_pass(); del d["http_observation_count"]
    assert module.evaluate(d)["status"] == "HOLD_FULL_MIXED"
    d = mixed_pass(); d["steady_state"]["rounds"] = 1
    assert module.evaluate(d)["status"] == "HOLD_FULL_MIXED"


def test_read_only_claim_recomputes_metrics_not_status_only():
    r = read_pass(); r["result"]["errors"] = 200
    assert not module.evaluate(None, r)["read_only_envelope_pass"]


def test_no_receipts_returns_hold_and_no_network_change():
    r = module.evaluate(None)
    assert r["status"] == "HOLD_FULL_MIXED"
    assert r["network_or_data_mutation"] is False


def test_cli_returns_nonzero_on_missing_full_receipt(tmp_path):
    read_path = tmp_path / "read.json"
    import json
    read_path.write_text(json.dumps(read_pass()))
    p = subprocess.run([sys.executable, str(SCRIPT), "--read-only", str(read_path)],
                       capture_output=True, text=True)
    assert p.returncode == 2
    assert json.loads(p.stdout)["read_only_envelope_pass"] is True


def test_cli_returns_zero_for_valid_synthetic_mixed_fixture(tmp_path):
    mixed_path = tmp_path / "mixed.json"
    import json
    mixed_path.write_text(json.dumps(mixed_pass()))
    p = subprocess.run([sys.executable, str(SCRIPT), "--mixed", str(mixed_path)],
                       capture_output=True, text=True)
    assert p.returncode == 0
    assert json.loads(p.stdout)["status"] == "FULL_MIXED_ACCEPTED"


def test_previously_accepted_1000_user_counts_cannot_be_used_as_5000_evidence():
    stale = mixed_pass()
    stale["profile"]["users"] = 1000
    stale["profile"]["projects"] = 3000
    stale["profile"]["conversations"] = 3000
    stale["profile"]["jobs"] = 3000
    stale["db"]["projects"] = 3000
    stale["db"]["threads"] = 3000
    stale["db"]["jobs_total"] = 3000
    stale["db"]["jobs_completed"] = 3000
    stale["unique_job_ids"] = 3000
    stale["ramp"] = [{"users": n} for n in (25, 100, 250, 500, 1000)]
    result = module.evaluate(stale, read_pass())
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "users" in result["failed_measured_conditions"]
    assert "ramp_reaches_5000" in result["failed_measured_conditions"]


def test_green_1000_user_read_only_cannot_count_as_5000_read_envelope():
    legacy = read_pass()
    legacy["profile"]["users"] = 1000
    legacy["profile"]["requests"] = 30000
    legacy["result"]["http_200"] = 30000
    assert module.evaluate(None, legacy)["read_only_envelope_pass"] is False


def test_capacity_ceiling_requires_15000_project_creation_timings():
    stale = mixed_pass()
    stale["latency"]["project_create"]["count"] = 14999
    stale["latency"]["conversation_create"]["count"] = 14999
    outcome = module.evaluate(stale)
    assert outcome["status"] == "HOLD_FULL_MIXED"
    assert "project_creation_api_covered" in outcome["failed_measured_conditions"]
    assert "conversation_creation_api_covered" in outcome["failed_measured_conditions"]


def test_steady_errors_cannot_disappear_from_top_level_error_totals():
    d = mixed_pass()
    d["steady_state"]["errors"] = 2000
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "consistent_steady_errors" in result["failed_measured_conditions"]


def test_http_observation_count_must_cover_all_distinct_route_families():
    d = mixed_pass()
    d["http_observation_count"] = 150000
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "consistent_total_request_observations" in result["failed_measured_conditions"]


def test_claiming_more_unique_jobs_than_created_fails_closed():
    d = mixed_pass()
    d["unique_job_ids"] = 20000
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "unique_job_ids_match_total" in result["failed_measured_conditions"]


def test_unaccounted_db_jobs_cannot_pass_as_fully_completed():
    d = mixed_pass()
    d["db"]["jobs_total"] = 16000
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "all_jobs_accounted_for" in result["failed_measured_conditions"]


def test_profile_counts_must_not_exceed_actual_db_asset_counts():
    d = mixed_pass()
    d["profile"]["projects"] = 16000
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "actual_assets_meet_profile" in result["failed_measured_conditions"]


def test_stale_profile_without_measured_authenticated_plateau_is_not_5000():
    d = mixed_pass()
    del d["steady_state"]["authenticated_active_users_min"]
    del d["steady_state"]["unique_authenticated_users"]
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "steady_authenticated_concurrency_measured" in result["failed_measured_conditions"]


def test_claiming_5000_unique_users_does_not_prove_5000_simultaneous_users():
    d = mixed_pass()
    d["steady_state"]["authenticated_active_users_min"] = 25
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "steady_authenticated_concurrency_measured" in result["failed_measured_conditions"]


def test_15m_total_elapsed_does_not_replace_15m_steady_window():
    d = mixed_pass()
    d["steady_state"]["window_start_epoch"] = 1890.0
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "15m_measured_steady_window" in result["failed_measured_conditions"]


def test_steady_window_cannot_be_outside_run_or_run_backwards():
    d = mixed_pass()
    d["steady_state"]["window_start_epoch"] = 900.0
    assert "15m_measured_steady_window" in module.evaluate(d)["failed_measured_conditions"]
    d = mixed_pass()
    d["steady_state"]["window_end_epoch"] = 2000.0
    assert "15m_measured_steady_window" in module.evaluate(d)["failed_measured_conditions"]
    d = mixed_pass()
    d["steady_state"]["window_end_epoch"] = 1005.0
    assert "15m_measured_steady_window" in module.evaluate(d)["failed_measured_conditions"]


def test_bad_steady_error_types_fail_closed_without_traceback():
    for value in ("0", True, None, -1, 150001):
        d = mixed_pass()
        d["steady_state"]["errors"] = value
        result = module.evaluate(d)
        assert result["status"] == "HOLD_FULL_MIXED"
        assert "consistent_steady_errors" in result["failed_measured_conditions"]


def test_minimum_concurrent_population_cannot_exceed_unique_identities():
    d = mixed_pass()
    d["steady_state"]["unique_authenticated_users"] = 4999
    result = module.evaluate(d)
    assert result["status"] == "HOLD_FULL_MIXED"
    assert "steady_authenticated_concurrency_measured" in result["failed_measured_conditions"]


def test_cli_rejects_internally_contradictory_capacity_receipt(tmp_path):
    import json
    d = mixed_pass()
    d["steady_state"]["errors"] = 180000
    d["error_count"] = 0
    file = tmp_path / "contradictory.json"
    file.write_text(json.dumps(d))
    run = subprocess.run(
        [sys.executable, str(SCRIPT), "--mixed", str(file)],
        capture_output=True, text=True, check=False, timeout=20,
    )
    assert run.returncode == 2
    report = json.loads(run.stdout)
    assert report["status"] == "HOLD_FULL_MIXED"
    assert "consistent_steady_errors" in report["failed_measured_conditions"]
    assert "Traceback" not in run.stderr


def test_unbounded_json_numbers_cannot_create_false_acceptance_or_crash():
    large = 10 ** 400
    for change, name in [
        (lambda d: d.update(error_count=large), "consistent_steady_errors"),
        (lambda d: d.update(http_observation_count=large), "consistent_total_request_observations"),
        (lambda d: d["steady_state"].update(p95_ms=large), "steady_read_p95"),
        (lambda d: d["profile"].update(users=large), "users"),
        (lambda d: d["steady_state"].update(authenticated_active_users_min=large), "steady_authenticated_concurrency_measured"),
    ]:
        receipt = mixed_pass()
        change(receipt)
        verdict = module.evaluate(receipt)
        assert verdict["status"] == "HOLD_FULL_MIXED"
        assert name in verdict["failed_measured_conditions"]


def test_unbounded_error_count_cli_returns_structured_hold(tmp_path):
    import json
    d = mixed_pass()
    d["error_count"] = 10 ** 400
    path = tmp_path / "overflow-metric.json"
    path.write_text(json.dumps(d))
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--mixed", str(path)],
        capture_output=True, text=True, check=False, timeout=20
    )
    assert proc.returncode == 2
    verdict = json.loads(proc.stdout)
    assert verdict["status"] == "HOLD_FULL_MIXED"
    assert "Traceback" not in proc.stderr
