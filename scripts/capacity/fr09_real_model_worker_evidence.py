"""Validate a *bounded* genuine-model + durable-worker pilot, never final FR09 GO.

The raw source is synthetic, isolated and not a production attestation. This
strictly checks the per-job PostgreSQL state, one claim/completion audit, tenant
ownership and actual-token fields recorded by a model-backed worker run. It
rejects worker jobs with deterministic fake-provider results.

This is structural evidence verification, not independent re-execution of
model output or a replacement for the full 5,000-user/15,000-model/72h gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

EXPECTED_SCHEMA = "aionex.fr09.true-worker-class-real-ollama-generated-token-db-audit.v1"
WORKER_SCHEMA = "aionex.fr09.real-projectworker-real-ollama-generated-token-pilot.v1"
WORKER_CLASS = "app.services.project_execution_worker.ProjectExecutionWorker"
EXPECTED_MODEL = "gemma3:4b"
EXPECTED_PROVIDER = "ollama"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MIN_PILOT_JOBS = 16
MAX_LOCAL_RECORDS = 15_000
MAX_RECEIPT_BYTES = 20_000_000


class ModelWorkerEvidenceError(ValueError):
    """A required real-model-backed worker claim failed closed."""


def strict_int(value: Any, name: str, least: int) -> int:
    if type(value) is not int or value < least:
        raise ModelWorkerEvidenceError(f"{name} must be integer >= {least}")
    return value


def strict_bool(value: Any, name: str, expected: bool) -> None:
    if value is not expected:
        raise ModelWorkerEvidenceError(f"{name} must be {expected}")


def finite_positive(value: Any, name: str) -> float:
    if type(value) not in (int, float):
        raise ModelWorkerEvidenceError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ModelWorkerEvidenceError(f"{name} must be finite and positive")
    return number


def opaque_identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ModelWorkerEvidenceError(f"{name} must be a bounded identifier")
    if any(ch.isspace() for ch in value):
        raise ModelWorkerEvidenceError(f"{name} must not contain whitespace")
    return value


def verified_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise ModelWorkerEvidenceError(f"{name} must be a lowercase SHA256 digest")
    return value


def _canonical_rows_digest(rows: list[dict[str, Any]]) -> str:
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_real_model_worker_pilot(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify each claim and model result in a pilot; full release stays HOLD.

    Generated-text hashes and counts are tied to the SQL state per job, but
    this verifier cannot independently observe the provider's runtime/network
    or prove model-quality/governance. Both remain separate gates.
    """
    if type(payload) is not dict or payload.get("schema") != EXPECTED_SCHEMA:
        raise ModelWorkerEvidenceError("unknown or absent model/worker receipt schema")
    for key in ("pilot_verified", "synthetic_bearer_tokens_erased",
                "production_container_identities_unchanged",
                "organization_seed_verified", "project_seed_verified",
                "execution_queue_verified", "real_model_worker_verified",
                "schema_migrated_offline"):
        strict_bool(payload.get(key), key, True)
    for key in ("production_touched", "production_dataset_touched",
                "real_model_15000_calls_proven", "full_workflow_governance_proven",
                "release_accepted"):
        strict_bool(payload.get(key), key, False)
    strict_int(payload.get("paid_provider_calls"), "paid_provider_calls", 0)
    if payload["paid_provider_calls"] != 0:
        raise ModelWorkerEvidenceError("pilot must never contain paid provider calls")
    if payload.get("other_isolated_containers_remaining") != []:
        raise ModelWorkerEvidenceError("unremoved isolated synthetic lab services")

    worker = payload.get("worker_and_model_evidence")
    if type(worker) is not dict or worker.get("schema") != WORKER_SCHEMA:
        raise ModelWorkerEvidenceError("missing real production worker class report")
    if worker.get("actual_worker_class") != WORKER_CLASS:
        raise ModelWorkerEvidenceError("real ProjectExecutionWorker class not proven")
    for key in ("AI_model_generated_output_verified",
                "all_job_rows_correlate_to_org_and_owner_and_audit"):
        strict_bool(worker.get(key), key, True)
    for key in ("test_did_not_use_real_AImodel", "full_provider_governance_executed",
                "full_release_accepted", "full_FR09_queue_and_external_provider_admission_accepted"):
        strict_bool(worker.get(key), key, False)
    if strict_int(worker.get("test_external_provider_requests"),
                  "test_external_provider_requests", 0) != 0:
        raise ModelWorkerEvidenceError("unexpected external provider request")
    if strict_int(worker.get("DB_approved_by_actual_AImodel"), "DB_approved_by_actual_AImodel", 0) != 0:
        raise ModelWorkerEvidenceError("pilot must never claim governance approval")
    if strict_int(worker.get("driver_exceptions"), "driver_exceptions", 0) != 0:
        raise ModelWorkerEvidenceError("model-backed worker has driver exceptions")

    rows = worker.get("per_job_evidence")
    if type(rows) is not list or not MIN_PILOT_JOBS <= len(rows) <= MAX_LOCAL_RECORDS:
        raise ModelWorkerEvidenceError("missing or unbounded per-job row evidence")
    size = len(rows)
    counts = (
        "requested_job_count", "claims_started_this_run",
        "python_execute_claim_completed_calls", "DB_completed_count",
        "real_lease_claim_audit_count", "real_worker_completion_audit_count",
        "verified_real_model_job_count", "verified_distinct_project_count",
    )
    for key in counts:
        if strict_int(worker.get(key), key, size) != size:
            raise ModelWorkerEvidenceError(f"{key} disagrees with per-job rows")
    if worker.get("DB_status_counts") != {"completed": size}:
        raise ModelWorkerEvidenceError("queued/running/failed/unexpected durable jobs remain")

    ids: set[str] = set()
    projects: set[str] = set()
    organizations: set[str] = set()
    owners: set[str] = set()
    sum_input = sum_output = 0
    for number, row in enumerate(rows):
        label = f"job[{number}]"
        if type(row) is not dict:
            raise ModelWorkerEvidenceError(f"{label} is not a full row")
        execution = opaque_identifier(row.get("execution_id"), f"{label}.execution_id")
        project = opaque_identifier(row.get("project_id"), f"{label}.project_id")
        org = opaque_identifier(row.get("organization_id"), f"{label}.organization_id")
        owner = opaque_identifier(row.get("requested_by_id"), f"{label}.requested_by_id")
        if execution in ids or project in projects:
            raise ModelWorkerEvidenceError("duplicate durable execution or project")
        ids.add(execution)
        projects.add(project)
        organizations.add(org)
        owners.add(owner)

        if row.get("status") != "completed" or row.get("approved") is not False:
            raise ModelWorkerEvidenceError(f"{label} is not a truthful terminal rework result")
        if row.get("provider") != EXPECTED_PROVIDER or row.get("model") != EXPECTED_MODEL:
            raise ModelWorkerEvidenceError(f"{label} is not a real local-model provider result")
        for key in ("real_model_response_observed_in_local_lab",
                    "project_owner_and_tenant_match", "claim_and_completion_audit_org_match",
                    "worker_lease_cleared", "synthetic_job"):
            strict_bool(row.get(key), f"{label}.{key}", True)
        strict_bool(row.get("full_governance_approved"), f"{label}.full_governance_approved", False)
        for key in ("worker_claim_audit_count", "worker_completion_audit_count",
                    "requests_count", "attempts"):
            if strict_int(row.get(key), f"{label}.{key}", 1) != 1:
                raise ModelWorkerEvidenceError(f"{label}.{key} != 1")
        strict_int(row.get("fencing_token"), f"{label}.fencing_token", 1)
        input_count = strict_int(row.get("input_tokens"), f"{label}.input_tokens", 1)
        output_count = strict_int(row.get("output_tokens"), f"{label}.output_tokens", 1)
        if strict_int(row.get("total_tokens"), f"{label}.total_tokens", 2) != input_count + output_count:
            raise ModelWorkerEvidenceError(f"{label} has inconsistent model token accounting")
        finite_positive(row.get("model_wall_ms"), f"{label}.model_wall_ms")
        verified_digest(row.get("prompt_sha256"), f"{label}.prompt_sha256")
        verified_digest(row.get("response_sha256"), f"{label}.response_sha256")
        sum_input += input_count
        sum_output += output_count

    if verified_digest(worker.get("per_job_evidence_sha256"), "per_job_evidence_sha256") != _canonical_rows_digest(rows):
        raise ModelWorkerEvidenceError("per-job evidence integrity digest mismatch")
    if strict_int(worker.get("verified_distinct_tenant_count"), "distinct_tenants", 1) != len(organizations):
        raise ModelWorkerEvidenceError("tenant count differs from model-backed job rows")
    if strict_int(worker.get("verified_real_model_input_tokens"), "aggregate_input_tokens", 1) != sum_input:
        raise ModelWorkerEvidenceError("persisted input-token aggregate mismatch")
    if strict_int(worker.get("verified_real_model_output_tokens"), "aggregate_output_tokens", 1) != sum_output:
        raise ModelWorkerEvidenceError("persisted output-token aggregate mismatch")
    finite_positive(worker.get("runtime_wall_clock_seconds"), "runtime_wall_clock_seconds")

    return {
        "schema": "aionex.fr09.verified-model-backed-real-worker-pilot.v1",
        "pilot_slice_verified": True,
        "real_worker_model_backed_jobs": size,
        "synthetic_distinct_tenants": len(organizations),
        "synthetic_distinct_projects": len(projects),
        "synthetic_distinct_users": len(owners),
        "verified_stored_input_tokens": sum_input,
        "verified_stored_output_tokens": sum_output,
        "per_job_manifest_sha256": worker["per_job_evidence_sha256"],
        "data_scope": "synthetic_isolated_postgresql",
        "raw_model_provider_io_independently_replayed_by_this_verifier": False,
        "full_production_model_governance_verified": False,
        "full_15000_model_inferences_accepted": False,
        "full_5000_user_15minute_mixed_load_accepted": False,
        "natural_72h_accepted": False,
        "final_release_accepted": False,
        "release_decision": "HOLD",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.stat().st_size > MAX_RECEIPT_BYTES:
        raise ModelWorkerEvidenceError("model-worker evidence file exceeds supported bound")
    source = args.receipt.read_bytes()
    data = json.loads(source)
    validated = verify_real_model_worker_pilot(data)
    validated["source_sha256"] = hashlib.sha256(source).hexdigest()
    print(json.dumps(validated, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
