"""Fail-closed FR09 provider-model policy RPM preflight, no provider calls.

Checks a deliberately sanitized, READ-ONLY and tenant-scoped snapshot of
currently validated model evidence. It does not read credentials, purchase
inference capacity, prove external account quota, or grant any deployment GO.

Model policy RPM caps are *optimistic* if each model has an independent limit.
They are never represented as a tested provider throughput or as license to
share one organization's provider credentials with another organization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

PROOF_SCHEMA = "aionex.fr09.readonly-model-policy-capacity-insufficiency.v2"
REQUIRED_CALLS = 15_000
PERIOD_MINUTES = 15
REQUIRED_PER_MINUTE = 1_000
MAX_DOCUMENT_BYTES = 256_000


class ProviderCapacityEvidenceError(ValueError):
    """The provider capacity report cannot satisfy this read-only preflight."""


def integer(value: Any, label: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ProviderCapacityEvidenceError(f"{label} must be integer >= {minimum}")
    return value


def number(value: Any, label: str) -> float:
    if type(value) not in (int, float):
        raise ProviderCapacityEvidenceError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ProviderCapacityEvidenceError(f"{label} must be finite and nonnegative")
    return result


def required_bool(value: Any, label: str, expected: bool) -> None:
    if value is not expected:
        raise ProviderCapacityEvidenceError(f"{label} must remain {expected}")


def verify_provider_capacity(payload: dict[str, Any]) -> dict[str, Any]:
    """Verify *only* policy-capacity evidence; full FR09 is always HOLD."""
    if type(payload) is not dict or payload.get("schema") != PROOF_SCHEMA:
        raise ProviderCapacityEvidenceError("unknown provider evidence schema")
    if payload.get("canonical_project") != "AIONEX AIOS":
        raise ProviderCapacityEvidenceError("unexpected target project")
    if not isinstance(payload.get("validated_model_policy_version"), str):
        raise ProviderCapacityEvidenceError("missing policy version")
    if not payload["validated_model_policy_version"].strip():
        raise ProviderCapacityEvidenceError("empty policy version")
    if payload.get("model_policy_routability_parser_used") != "DurableProjectAIResolver._parse_model":
        raise ProviderCapacityEvidenceError("original live model routability parser not attested")
    timestamp = payload.get("captured_utc")
    if not isinstance(timestamp, str):
        raise ProviderCapacityEvidenceError("snapshot timestamp missing")
    try:
        captured = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProviderCapacityEvidenceError("invalid captured timestamp") from exc
    if captured.tzinfo is None:
        raise ProviderCapacityEvidenceError("snapshot timestamp lacks timezone")

    for key in (
        "actual_account_provider_quota_verified",
        "validated_model_allowed_by_each_tenant_policy_verified",
        "synthetic_100_tenants_provider_authorities_validated",
        "provider_credentials_read", "provider_names_or_ids_or_customer_data_exported",
        "provider_evidence_update_performed", "production_postgresql_write_performed",
        "production_container_mutation", "full_15000_model_inference_accepted",
        "full_5000_active_mixed_model_load_accepted", "final_release_accepted",
    ):
        required_bool(payload.get(key), key, False)
    for key in ("real_inference_requests_executed_by_this_readonly_audit",
                "paid_provider_requests_executed"):
        if integer(payload.get(key), key) != 0:
            raise ProviderCapacityEvidenceError("read-only audit must never call providers")
    if payload.get("release_decision") != "HOLD_PROVIDER_CAPACITY_NOT_PROVEN":
        raise ProviderCapacityEvidenceError("provider audit may not authorize launch")
    if integer(payload.get("required_genuine_calls"), "required_genuine_calls") != REQUIRED_CALLS:
        raise ProviderCapacityEvidenceError("required inference target was weakened")
    if integer(payload.get("full_profile_minutes"), "full_profile_minutes") != PERIOD_MINUTES:
        raise ProviderCapacityEvidenceError("test duration differs from canonical 15 minutes")
    if integer(payload.get("required_real_model_calls_per_minute"), "required_rpm") != REQUIRED_PER_MINUTE:
        raise ProviderCapacityEvidenceError("minimum 1,000 model calls per minute required")

    counts = payload.get("provider_counts")
    if type(counts) is not dict:
        raise ProviderCapacityEvidenceError("provider inventory count summary missing")
    total_providers = integer(counts.get("provider_records_seen"), "provider_records_seen")
    connected = integer(counts.get("connected_enabled"), "connected_enabled")
    fresh = integer(counts.get("fresh_validated_models"), "fresh_validated_models")
    expired = integer(counts.get("stale_validated_models"), "stale_validated_models")
    malformed = integer(counts.get("not_routable_validated_records"), "not_routable_rows")
    empty = integer(counts.get("connected_without_validation"), "connected_without_validation")
    if connected > total_providers or empty > connected:
        raise ProviderCapacityEvidenceError("provider inventory counts are contradictory")

    entries = payload.get("per_provider_sanitized_status")
    if type(entries) is not list or len(entries) != connected:
        raise ProviderCapacityEvidenceError("connected provider status rows missing")
    total_fresh = total_invalid = without_evidence = 0
    total_rpm = 0
    active_types: set[str] = set()
    for n, row in enumerate(entries):
        if type(row) is not dict:
            raise ProviderCapacityEvidenceError("provider entry must be object")
        category = row.get("type")
        if not isinstance(category, str) or not category.strip() or len(category) > 64:
            raise ProviderCapacityEvidenceError(f"provider[{n}] invalid category")
        c = integer(row.get("fresh"), f"provider[{n}].fresh")
        invalid = integer(row.get("stale_or_invalid"), f"provider[{n}].invalid")
        list_models = row.get("validated_model_limits")
        if list_models is None:
            if row.get("connected_but_missing_validated_models") is not True or c or invalid:
                raise ProviderCapacityEvidenceError("connected provider evidence not classified")
            without_evidence += 1
            list_models = []
        elif type(list_models) is not list or len(list_models) != c:
            raise ProviderCapacityEvidenceError("fresh model count differs from model-policy rows")
        if c:
            active_types.add(category)
        for model in list_models:
            if type(model) is not dict:
                raise ProviderCapacityEvidenceError("model policy must be object")
            rpm = integer(model.get("model_policy_requests_per_minute"), "model_rpm", 1)
            concurrent = integer(model.get("model_policy_concurrency"), "model_concurrency", 1)
            if not 1 <= rpm <= 100_000 or concurrent > 10_000:
                raise ProviderCapacityEvidenceError("unbounded policy limits")
            for proof_flag in ("model_name_present","evidence_ref_present","policy_ref_present"):
                if model.get(proof_flag) is not True:
                    raise ProviderCapacityEvidenceError(
                        "model policy missing required nonsecret evidence marker"
                    )
            left = number(model.get("expires_in_hours"), "expires_in_hours")
            if left < PERIOD_MINUTES / 60:
                raise ProviderCapacityEvidenceError(
                    "model evidence does not cover the full 15-minute acceptance window"
                )
            total_rpm += rpm
        total_fresh += c
        total_invalid += invalid
    if total_fresh != fresh or total_invalid != expired + malformed or without_evidence != empty:
        raise ProviderCapacityEvidenceError("model evidence status counters disagree")

    groups = payload.get("optimistic_capacity_across_all_validated_models")
    if type(groups) is not list or not groups or len(groups) > connected:
        raise ProviderCapacityEvidenceError("org-scoped provider model groups missing")
    if integer(payload.get("provider_organizations_with_fresh_validated_evidence"),
               "provider_organizations_with_fresh_validated_evidence", 1) != len(groups):
        raise ProviderCapacityEvidenceError("provider organization count mismatch")
    model_count_sum = org_rpm_sum = 0
    org_types: set[str] = set()
    for n, org in enumerate(groups):
        if type(org) is not dict:
            raise ProviderCapacityEvidenceError("organization evidence group must be object")
        model_count_sum += integer(org.get("fresh_models"), f"group[{n}].models", 1)
        rpm = integer(org.get("optimistic_independent_model_policy_calls_per_minute"), f"group[{n}].rpm", 1)
        org_rpm_sum += rpm
        allowed_types = org.get("types")
        if type(allowed_types) is not list or not allowed_types:
            raise ProviderCapacityEvidenceError("organization has no model type list")
        if len(set(allowed_types)) != len(allowed_types):
            raise ProviderCapacityEvidenceError("duplicate provider types in organization")
        if any(t not in active_types for t in allowed_types):
            raise ProviderCapacityEvidenceError("organization model uses unvalidated provider")
        org_types.update(allowed_types)
        if integer(org.get("optimistic_calls_at_15_minutes"), f"group[{n}].15min") != PERIOD_MINUTES*rpm:
            raise ProviderCapacityEvidenceError("model policy window is inconsistent")
        if integer(org.get("optimistic_shortfall_at_15_minutes"), f"group[{n}].shortfall") != max(0,REQUIRED_CALLS-PERIOD_MINUTES*rpm):
            raise ProviderCapacityEvidenceError("model policy group understates missing calls")
        number(org.get("lowest_evidence_validity_remaining_hours"), f"group[{n}].ttl")
    if model_count_sum != fresh or total_rpm != org_rpm_sum or org_types != active_types:
        raise ProviderCapacityEvidenceError("provider model count/rate and tenant groups differ")

    total = integer(payload.get("optimistic_sum_independent_model_policy_rpm"), "total_policy_rpm")
    if total != total_rpm:
        raise ProviderCapacityEvidenceError("reported total policy RPM is inconsistent")
    if integer(payload.get("optimistic_sum_independent_model_policy_calls_at_15min"), "total_policy_calls") != total*PERIOD_MINUTES:
        raise ProviderCapacityEvidenceError("reported 15-minute policy capacity inconsistent")
    call_gap = max(0, REQUIRED_CALLS-total*PERIOD_MINUTES)
    rpm_gap = max(0, REQUIRED_PER_MINUTE-total)
    if integer(payload.get("optimistic_shortfall_calls_in_15min"), "call_shortfall") != call_gap:
        raise ProviderCapacityEvidenceError("missing calls were understated")
    if integer(payload.get("capacity_shortfall_calls_per_minute"), "rpm_shortfall") != rpm_gap:
        raise ProviderCapacityEvidenceError("RPM shortfall was understated")
    return {
        "schema":"aionex.fr09.sanitized-policy-inference-capacity-preflight.v1",
        "policy_snapshot_verified_internally":True,
        "fresh_validated_models":fresh,
        "connected_providers_without_validated_model_evidence":empty,
        "model_evidence_orgs":len(groups),
        "optimistic_total_rpm":total,
        "optimistic_15min_model_calls":total*PERIOD_MINUTES,
        "required_calls":REQUIRED_CALLS,
        "required_rpm":REQUIRED_PER_MINUTE,
        "optimistic_missing_calls":call_gap,
        "optimistic_rpm_shortfall":rpm_gap,
        "rate_meets_requirement_even_before_account_quota":total>=REQUIRED_PER_MINUTE,
        "no_external_account_quota_proved":True,
        "tenant_specific_provider_scope_not_proven":True,
        "zero_paid_calls_during_audit":True,
        "provider_api_independent_throughput_verified":False,
        "complete_15000_real_model_inferences_proved":False,
        "full_release_accepted":False,
        "decision":"HOLD",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt",type=Path,required=True)
    args = parser.parse_args()
    if args.receipt.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ProviderCapacityEvidenceError("provider policy evidence exceeds size limit")
    payload=args.receipt.read_bytes()
    verified=verify_provider_capacity(json.loads(payload))
    verified["source_sha256"]=hashlib.sha256(payload).hexdigest()
    print(json.dumps(verified,sort_keys=True,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
