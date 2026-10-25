"""FR09 genuine-model per-job manifest: positive pilot and fail-closed negatives."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.capacity.fr09_real_model_worker_evidence import (
    ModelWorkerEvidenceError,
    verify_real_model_worker_pilot,
)

ROOT = Path(__file__).resolve().parents[1]
PROOF = (
    ROOT / "docs/project/receipts"
    / "FR09-20261025-16-REAL-MODEL-WORKER-PER-JOB-PROOF.json"
)
SHA256 = "dcab6e3ba4b158a4ecd357f0dd548f97f963604cbff19c789d1673667c812b8e"


def source() -> dict:
    raw = PROOF.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA256
    return json.loads(raw)


def rehash(payload: dict) -> None:
    worker = payload["worker_and_model_evidence"]
    rows = worker["per_job_evidence"]
    worker["per_job_evidence_sha256"] = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def test_verified_per_job_real_model_pilot_stays_pilot_not_release():
    sample = source()
    prior = deepcopy(sample)
    result = verify_real_model_worker_pilot(sample)
    assert result["pilot_slice_verified"] is True
    assert result["real_worker_model_backed_jobs"] == 16
    assert result["synthetic_distinct_projects"] == 16
    assert result["synthetic_distinct_tenants"] == 4
    assert result["synthetic_distinct_users"] == 16
    assert result["verified_stored_output_tokens"] == 48
    assert result["verified_stored_input_tokens"] == 2018
    assert result["raw_model_provider_io_independently_replayed_by_this_verifier"] is False
    assert result["full_15000_model_inferences_accepted"] is False
    assert result["full_production_model_governance_verified"] is False
    assert result["full_5000_user_15minute_mixed_load_accepted"] is False
    assert result["natural_72h_accepted"] is False
    assert result["final_release_accepted"] is False
    assert result["release_decision"] == "HOLD"
    assert sample == prior


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("pilot_verified",), False),
        (("organization_seed_verified",), False),
        (("project_seed_verified",), False),
        (("execution_queue_verified",), False),
        (("real_model_worker_verified",), False),
        (("schema_migrated_offline",), False),
        (("synthetic_bearer_tokens_erased",), False),
        (("production_container_identities_unchanged",), False),
        (("production_touched",), True),
        (("production_dataset_touched",), True),
        (("full_workflow_governance_proven",), True),
        (("real_model_15000_calls_proven",), True),
        (("release_accepted",), True),
        (("other_isolated_containers_remaining",), ["leftover"]),
        (("paid_provider_calls",), 1),
        (("worker_and_model_evidence", "actual_worker_class"), "fake_worker"),
        (("worker_and_model_evidence", "test_did_not_use_real_AImodel"), True),
        (("worker_and_model_evidence", "AI_model_generated_output_verified"), False),
        (("worker_and_model_evidence", "full_provider_governance_executed"), True),
        (("worker_and_model_evidence", "driver_exceptions"), 1),
        (("worker_and_model_evidence", "DB_completed_count"), 15),
        (("worker_and_model_evidence", "requested_job_count"), 15000),
        (("worker_and_model_evidence", "verified_real_model_job_count"), 15000),
        (("worker_and_model_evidence", "real_lease_claim_audit_count"), 15),
        (("worker_and_model_evidence", "real_worker_completion_audit_count"), 17),
        (("worker_and_model_evidence", "verified_real_model_output_tokens"), 0),
        (("worker_and_model_evidence", "verified_distinct_tenant_count"), 5),
        (("worker_and_model_evidence", "DB_status_counts"), {"queued": 15, "completed": 1}),
    ],
)
def test_fails_for_aggregate_and_safety_tampering(path, replacement):
    sample = source()
    changed = sample
    for part in path[:-1]:
        changed = changed[part]
    changed[path[-1]] = replacement
    with pytest.raises(ModelWorkerEvidenceError):
        verify_real_model_worker_pilot(sample)


@pytest.mark.parametrize(
    ("key", "replacement"),
    [
        ("status", "queued"),
        ("approved", True),
        ("provider", "offline-synthetic-only"),
        ("model", "sha256-not-AI-inference"),
        ("real_model_response_observed_in_local_lab", False),
        ("project_owner_and_tenant_match", False),
        ("claim_and_completion_audit_org_match", False),
        ("worker_lease_cleared", False),
        ("worker_claim_audit_count", 0),
        ("worker_completion_audit_count", 2),
        ("requests_count", 0),
        ("attempts", 2),
        ("fencing_token", 0),
        ("input_tokens", 0),
        ("output_tokens", 0),
        ("total_tokens", 10_000),
        ("prompt_sha256", "not-a-provider-prompt-hash"),
        ("response_sha256", "0" * 63 + "x"),
        ("model_wall_ms", 0),
        ("full_governance_approved", True),
    ],
)
def test_rehash_cannot_make_invalid_worker_row_pass(key, replacement):
    sample = source()
    sample["worker_and_model_evidence"]["per_job_evidence"][0][key] = replacement
    rehash(sample)
    with pytest.raises(ModelWorkerEvidenceError):
        verify_real_model_worker_pilot(sample)


def test_duplicate_project_across_distinct_jobs_fails_even_when_rehashed():
    payload = source()
    records = payload["worker_and_model_evidence"]["per_job_evidence"]
    records[1]["project_id"] = records[0]["project_id"]
    rehash(payload)
    with pytest.raises(ModelWorkerEvidenceError, match="duplicate"):
        verify_real_model_worker_pilot(payload)


def test_duplicate_execution_across_distinct_projects_fails_even_when_rehashed():
    payload = source()
    records = payload["worker_and_model_evidence"]["per_job_evidence"]
    records[1]["execution_id"] = records[0]["execution_id"]
    rehash(payload)
    with pytest.raises(ModelWorkerEvidenceError, match="duplicate"):
        verify_real_model_worker_pilot(payload)


def test_changing_output_sha_requires_reliable_source_manifest():
    payload = source()
    records = payload["worker_and_model_evidence"]["per_job_evidence"]
    records[0]["response_sha256"] = "0" * 64
    with pytest.raises(ModelWorkerEvidenceError, match="integrity digest"):
        verify_real_model_worker_pilot(payload)
    # A forged valid-looking digest is not independent proof of an API call.
    rehash(payload)
    result = verify_real_model_worker_pilot(payload)
    assert result["raw_model_provider_io_independently_replayed_by_this_verifier"] is False
    assert result["final_release_accepted"] is False


def test_fake_15000_durable_jobs_cannot_substitute_for_real_model_manifest():
    payload = source()
    worker = payload["worker_and_model_evidence"]
    worker["verified_real_model_job_count"] = 15000
    worker["DB_completed_count"] = 15000
    worker["requested_job_count"] = 15000
    with pytest.raises(ModelWorkerEvidenceError):
        verify_real_model_worker_pilot(payload)


def test_model_only_batch_receipt_is_not_real_worker_job_proof():
    with pytest.raises(ModelWorkerEvidenceError, match="schema"):
        verify_real_model_worker_pilot({
            "schema": "aionex.fr09.genuine-gemma3-4b-offline-cpu-inference-throughput.v1",
            "verified_model_calls_total": 73,
            "sample_verified": True,
        })


def test_missing_per_job_records_cannot_be_covered_by_total_success():
    payload = source()
    payload["worker_and_model_evidence"].pop("per_job_evidence")
    with pytest.raises(ModelWorkerEvidenceError, match="per-job"):
        verify_real_model_worker_pilot(payload)


@pytest.mark.parametrize("bad_number", [True, "16", 16.0, None, -1])
def test_job_count_is_a_strict_integer(bad_number):
    sample = source()
    sample["worker_and_model_evidence"]["DB_completed_count"] = bad_number
    with pytest.raises(ModelWorkerEvidenceError):
        verify_real_model_worker_pilot(sample)
