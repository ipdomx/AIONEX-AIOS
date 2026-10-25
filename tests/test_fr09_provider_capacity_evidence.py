"""FR09 15,000 real-model-call capacity: fail closed on internal policy limits."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.capacity.fr09_provider_capacity_evidence import (
    ProviderCapacityEvidenceError,
    verify_provider_capacity,
)

FILE = (
    Path(__file__).resolve().parents[1]
    / "docs/project/receipts/FR09-20261025-PROVIDER-MODEL-CAPACITY-READONLY-V2-HOLD.json"
)
EXPECTED_SHA256 = "415aaae17ce33fde514eaff07fadcb2c524e41cbc340b0882696fb15ea7fc76d"


def source() -> dict:
    data = FILE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == EXPECTED_SHA256
    return json.loads(data)


def test_actual_readonly_evidence_proves_policy_shortfall_only():
    raw = source()
    snapshot = deepcopy(raw)
    result = verify_provider_capacity(raw)
    assert result["policy_snapshot_verified_internally"] is True
    assert result["fresh_validated_models"] == 5
    assert result["model_evidence_orgs"] == 1
    assert result["connected_providers_without_validated_model_evidence"] == 10
    assert result["optimistic_total_rpm"] == 360
    assert result["optimistic_15min_model_calls"] == 5400
    assert result["optimistic_missing_calls"] == 9600
    assert result["optimistic_rpm_shortfall"] == 640
    assert result["required_rpm"] == 1000
    assert result["rate_meets_requirement_even_before_account_quota"] is False
    assert result["no_external_account_quota_proved"] is True
    assert result["tenant_specific_provider_scope_not_proven"] is True
    assert result["provider_api_independent_throughput_verified"] is False
    assert result["full_release_accepted"] is False
    assert result["decision"] == "HOLD"
    assert raw == snapshot


@pytest.mark.parametrize(
    ("field","alteration"),
    [
        ("provider_credentials_read",True),
        ("provider_names_or_ids_or_customer_data_exported",True),
        ("provider_evidence_update_performed",True),
        ("production_postgresql_write_performed",True),
        ("production_container_mutation",True),
        ("paid_provider_requests_executed",1),
        ("real_inference_requests_executed_by_this_readonly_audit",1),
        ("final_release_accepted",True),
        ("full_15000_model_inference_accepted",True),
        ("full_5000_active_mixed_model_load_accepted",True),
        ("actual_account_provider_quota_verified",True),
        ("validated_model_allowed_by_each_tenant_policy_verified",True),
        ("synthetic_100_tenants_provider_authorities_validated",True),
        ("required_genuine_calls",14999),
        ("full_profile_minutes",14),
        ("required_real_model_calls_per_minute",999),
        ("release_decision","GO"),
        ("canonical_project","AIONEX Trading"),
        ("optimistic_sum_independent_model_policy_rpm",1000),
        ("optimistic_sum_independent_model_policy_calls_at_15min",15000),
        ("optimistic_shortfall_calls_in_15min",0),
        ("capacity_shortfall_calls_per_minute",0),
        ("provider_organizations_with_fresh_validated_evidence",100),
        ("schema","garbage"),
    ],
)
def test_rejects_false_go_and_fake_rpm_capacity(field, alteration):
    payload = source()
    payload[field] = alteration
    with pytest.raises(ProviderCapacityEvidenceError):
        verify_provider_capacity(payload)


@pytest.mark.parametrize("field",["provider_records_seen","connected_enabled",
    "fresh_validated_models","stale_validated_models","not_routable_validated_records",
    "connected_without_validation"])
def test_rejects_contradictory_inventory_counts(field):
    payload=source()
    # The total reported inventory is allowed to contain disabled providers.
    # It becomes inconsistent only when below the connected count.
    payload["provider_counts"][field] = 1 if field == "provider_records_seen" else 10_000
    with pytest.raises(ProviderCapacityEvidenceError):
        verify_provider_capacity(payload)


@pytest.mark.parametrize(
    ("key","bad"),
    [
        ("model_policy_requests_per_minute",0),
        ("model_policy_requests_per_minute",100001),
        ("model_policy_requests_per_minute","15000"),
        ("model_policy_concurrency",0),
        ("model_policy_concurrency",10001),
        ("expires_in_hours",0),
        ("expires_in_hours",0.2),
        ("expires_in_hours",float("nan")),
        ("expires_in_hours",float("inf")),
    ],
)
def test_model_entry_cannot_exaggerate_or_forge_policy_evidence(key,bad):
    payload=source()
    row=next(x for x in payload["per_provider_sanitized_status"] if x["fresh"])
    row["validated_model_limits"][0][key]=bad
    with pytest.raises(ProviderCapacityEvidenceError):
        verify_provider_capacity(payload)


@pytest.mark.parametrize("evidence_flag",[
    "model_name_present", "evidence_ref_present", "policy_ref_present",
])
def test_fresh_model_must_keep_nonsecret_live_authorization_markers(evidence_flag):
    payload=source()
    provider=next(row for row in payload["per_provider_sanitized_status"] if row["fresh"])
    provider["validated_model_limits"][0][evidence_flag]=False
    with pytest.raises(ProviderCapacityEvidenceError,match="nonsecret"):
        verify_provider_capacity(payload)


def test_model_rpm_summary_must_match_each_individual_entry():
    payload=source()
    row=next(x for x in payload["per_provider_sanitized_status"] if x["fresh"])
    row["validated_model_limits"][0]["model_policy_requests_per_minute"]+=200
    with pytest.raises(ProviderCapacityEvidenceError,match="model count/rate"):
        verify_provider_capacity(payload)


def test_missing_connected_provider_evidence_cannot_be_ignored():
    payload=source()
    row=next(x for x in payload["per_provider_sanitized_status"] if x["fresh"]==0
             and x.get("connected_but_missing_validated_models") is True)
    row.pop("connected_but_missing_validated_models")
    with pytest.raises(ProviderCapacityEvidenceError):
        verify_provider_capacity(payload)


def test_provider_org_cannot_claim_more_than_validated_models():
    payload=source()
    payload["optimistic_capacity_across_all_validated_models"][0]["fresh_models"]=5000
    with pytest.raises(ProviderCapacityEvidenceError):
        verify_provider_capacity(payload)


def test_provider_org_cannot_steal_an_unvalidated_model():
    payload=source()
    payload["optimistic_capacity_across_all_validated_models"][0]["types"]=["ollama"]
    with pytest.raises(ProviderCapacityEvidenceError):
        verify_provider_capacity(payload)


def test_connected_status_is_not_validated_model_evidence():
    payload=source()
    payload["provider_counts"]["fresh_validated_models"]=14
    with pytest.raises(ProviderCapacityEvidenceError):
        verify_provider_capacity(payload)


def test_not_even_optimistic_cap_sufficiency_is_a_final_go():
    payload=source()
    # A separate approved provider model might raise policy RPM, but
    # this read-only snapshot still has no account quota, tenant authority,
    # or genuine model executions.
    entry=next(x for x in payload["per_provider_sanitized_status"] if x["type"]=="deepseek")
    entry["validated_model_limits"][0]["model_policy_requests_per_minute"]=800
    org=payload["optimistic_capacity_across_all_validated_models"][0]
    org["optimistic_independent_model_policy_calls_per_minute"]=1040
    org["optimistic_calls_at_15_minutes"]=15600
    org["optimistic_shortfall_at_15_minutes"]=0
    payload["optimistic_sum_independent_model_policy_rpm"]=1040
    payload["optimistic_sum_independent_model_policy_calls_at_15min"]=15600
    payload["optimistic_shortfall_calls_in_15min"]=0
    payload["capacity_shortfall_calls_per_minute"]=0
    result=verify_provider_capacity(payload)
    assert result["rate_meets_requirement_even_before_account_quota"] is True
    assert result["full_release_accepted"] is False
    assert result["provider_api_independent_throughput_verified"] is False
    assert result["decision"]=="HOLD"


@pytest.mark.parametrize("payload", [None, [], "", {"schema":"other"}])
def test_rejects_non_source_and_missing_schema(payload):
    with pytest.raises(ProviderCapacityEvidenceError):
        verify_provider_capacity(payload)
