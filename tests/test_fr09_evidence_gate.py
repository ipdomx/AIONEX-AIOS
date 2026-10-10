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
        "profile": {"users": 1000, "projects": 3000, "conversations": 3000, "jobs": 3000,
                    "steady_seconds": 900},
        "ramp": [{"users": n} for n in (25, 100, 250, 500, 1000)],
        "checks": {key: True for key in module.REQUIRED_FLAGS},
        "db": {"projects": 3000, "threads": 3000, "jobs_total": 3000,
               "jobs_completed": 3000, "jobs_queued": 0, "jobs_running": 0,
               "jobs_failed": 0, "jobs_cancelled": 0, "jobs_needs_review": 0,
               "tenant_mismatch_jobs": 0},
        "steady_state": {"rounds": 30, "requests": 30000, "p95_ms": 27.3, "errors": 0},
        "latency": {"auth_read": {"p95_ms": 70}, "enqueue": {"p95_ms": 110},
                    "project_create": {"count": 3000},
                    "conversation_create": {"count": 3000}},
        "cross_tenant_negative_pass": 1000, "unique_job_ids": 3000,
        "http_observation_count": 36875, "error_count": 0,
        "provider": {"external_calls": 0, "provider_spend_usd": 0.0},
    }


def read_pass():
    return {
        "status": "PASS_EXACT_MERGED_15M_READ_SLO",
        "profile": {"users": 1000, "requests": 30000, "rounds": 30},
        "result": {"http_200": 30000, "errors": 0, "max_shard_p95_ms": 17.135},
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
