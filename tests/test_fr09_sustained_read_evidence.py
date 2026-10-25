"""Negative-test the FR09 15-minute read slice without network or model calls."""
from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.capacity.fr09_sustained_read_evidence import (
    ReadEvidenceError,
    verify_sustained_read_slice,
)

ROUTES = ("identity", "projects", "conversations")


def valid_receipt() -> dict:
    return {
        "test_passed": True,
        "production_changed": False,
        "original_live_production_container_identities_unchanged": True,
        "synthetic_bearer_tokens_destroyed": True,
        "sustained_15min_synthetic_reads_proved": True,
        "full_5000_sustained_capacity_accepted": False,
        "lab_containers_remaining": 0,
        "synthetic_cohort_size": 5000,
        "synthetic_tenant_rows": 100,
        "synthetic_project_rows": 15000,
        "synthetic_task_rows": 15000,
        "synthetic_conversation_rows": 15000,
        "steady_state_minutes": 15,
        "steady_state_elapsed_seconds": 900.25,
        "offered_requests_per_second": 250.0,
        "per_minute_read_metrics": [
            {
                "minute": i, "started_at_utc": f"2026-10-25T18:{i:02d}:00Z",
                "total_expected": 15000, "completed_http_200": 15000,
                "minute_end_lateness_ms": 0.5,
                "route_p95_ms": {"identity": 20.1, "projects": 32.2, "conversations": 25.3},
            }
            for i in range(1, 16)
        ],
        "measurements": [
            {"stage": "candidate5000_page", "measurement": [
                {"path": route, "requests": 75000,
                 "success_200": 75000, "p95_ms": 35.2}
                for route in ROUTES
            ]}
        ],
    }


def test_15_complete_minutes_can_pass_only_the_paced_read_slice():
    value = verify_sustained_read_slice(valid_receipt())
    assert value["read_slice_verified"] is True
    assert value["http200_total"] == 225000
    assert value["steady_state_minutes"] == 15
    assert value["synthetic_authenticated_users"] == 5000
    assert value["distinct_synthetic_tenants"] == 100
    assert value["full_5000_simultaneous_requests_accepted"] is False
    assert value["actual_15000_model_inferences_proven"] is False
    assert value["final_release_accepted"] is False
    assert value["release_decision"] == "HOLD"


@pytest.mark.parametrize(
    ("key", "replacement"),
    [
        ("test_passed", False),
        ("sustained_15min_synthetic_reads_proved", False),
        ("original_live_production_container_identities_unchanged", False),
        ("synthetic_bearer_tokens_destroyed", False),
        ("production_changed", True),
        ("lab_containers_remaining", 1),
        ("synthetic_cohort_size", 4999),
        ("synthetic_tenant_rows", 99),
        ("synthetic_project_rows", 14999),
        ("synthetic_task_rows", 14999),
        ("synthetic_conversation_rows", 14999),
        ("steady_state_minutes", 14),
        ("steady_state_elapsed_seconds", 899.95),
        ("steady_state_elapsed_seconds", 966.0),
        ("offered_requests_per_second", 160.0),
        ("full_5000_sustained_capacity_accepted", True),
    ],
)
def test_fails_if_required_scalar_evidence_is_absent_or_weakened(key, replacement):
    payload = valid_receipt()
    payload[key] = replacement
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(payload)


def test_rejects_missing_minute_even_if_aggregate_routes_succeed():
    data = valid_receipt()
    data["per_minute_read_metrics"].pop()
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(data)


def test_rejects_reordered_minute():
    data = valid_receipt()
    data["per_minute_read_metrics"][7]["minute"] = 7
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(data)


def test_rejects_hidden_per_minute_error():
    data = valid_receipt()
    data["per_minute_read_metrics"][9]["completed_http_200"] = 14999
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(data)


def test_rejects_bad_minute_route_p95_even_if_full_15min_p95_is_good():
    data = valid_receipt()
    data["per_minute_read_metrics"][14]["route_p95_ms"]["projects"] = 500.01
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(data)


def test_rejects_restricted_generator_backlog():
    data = valid_receipt()
    data["per_minute_read_metrics"][0]["minute_end_lateness_ms"] = 2000.01
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(data)


def test_rejects_aggregate_route_over_p95():
    data = valid_receipt()
    data["measurements"][0]["measurement"][0]["p95_ms"] = 500.01
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(data)


def test_rejects_incomplete_per_user_per_route_responses():
    data = valid_receipt()
    data["measurements"][0]["measurement"][1]["success_200"] = 74999
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(data)


def test_rejects_duplicate_route_summary():
    data = valid_receipt()
    data["measurements"][0]["measurement"][1]["path"] = "identity"
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(data)


def test_rejects_synthetic_short_run_given_15minute_label():
    data = valid_receipt()
    data["steady_state_elapsed_seconds"] = 60.0
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(data)


def test_read_validation_does_not_mutate_source():
    source = valid_receipt()
    identical = deepcopy(source)
    verify_sustained_read_slice(source)
    assert source == identical


def test_missing_elapsed_must_provide_original_runner_attestation():
    report = valid_receipt()
    del report["steady_state_elapsed_seconds"]
    with pytest.raises(ReadEvidenceError, match="driver attestation"):
        verify_sustained_read_slice(report)


def test_source_attested_elapsed_is_explicitly_lower_confidence(tmp_path):
    driver = tmp_path / "sealed-runner.py"
    driver.write_text(
        'assert observed["steady_state_elapsed_seconds"] >= 900\n'
        'assert observed["steady_state_minutes"] == 15\n'
        'result["sustained_15min_synthetic_reads_proved"]=True\n'
    )
    report = valid_receipt()
    del report["steady_state_elapsed_seconds"]
    result = verify_sustained_read_slice(report, driver_source=driver)
    assert result["read_slice_verified"] is True
    assert result["observed_duration_s"] is None
    assert result["elapsed_evidence_mode"] == "source_attested_minimum_900s_not_directly_persisted"
    assert result["minute_ends_span_seconds"] == 14 * 60
    assert len(result["source_driver_sha256"]) == 64
    assert result["final_release_accepted"] is False


def test_incomplete_runner_attestation_cannot_override_missing_elapsed(tmp_path):
    driver = tmp_path / "unsafe-runner.py"
    driver.write_text('result["sustained_15min_synthetic_reads_proved"]=True\n')
    report = valid_receipt()
    del report["steady_state_elapsed_seconds"]
    with pytest.raises(ReadEvidenceError, match="source gate"):
        verify_sustained_read_slice(report, driver_source=driver)


def test_attested_driver_cannot_make_fake_minute_timestamps_pass(tmp_path):
    driver = tmp_path / "sealed-runner.py"
    driver.write_text(
        'assert observed["steady_state_elapsed_seconds"] >= 900\n'
        'assert observed["steady_state_minutes"] == 15\n'
        'result["sustained_15min_synthetic_reads_proved"]=True\n'
    )
    report = valid_receipt()
    del report["steady_state_elapsed_seconds"]
    report["per_minute_read_metrics"][-1]["started_at_utc"] = "2026-10-25T18:01:00Z"
    with pytest.raises(ReadEvidenceError):
        verify_sustained_read_slice(report, driver_source=driver)
