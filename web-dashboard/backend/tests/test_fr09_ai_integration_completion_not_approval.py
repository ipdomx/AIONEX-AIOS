"""A model-only ProjectExecution integration cannot claim full project approval."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.services.project_execution_worker import ProjectExecutionWorker


def synthetic_partial_result(*, approved=True, score=1.0):
    return {
        "success": True,
        "approved": approved,
        "readiness_score": score,
        "requests_count": 1,
        "provider": "ollama",
        "model": "gemma3:4b",
        "integration_foundation": True,
        "all_governance_layers_executed": False,
        "model_claims_used_as_execution_proof": False,
        "production_modified": False,
        "output_tokens": 3,
    }


def test_partial_live_inference_cannot_approve_even_if_runner_claims_true():
    result=synthetic_partial_result()
    pristine=copy.deepcopy(result)
    protected=ProjectExecutionWorker._truthful_completion_summary(result)
    assert protected["success"] is True
    assert protected["approved"] is False
    assert protected["readiness_score"] == 0.0
    assert protected["release_approval_withheld"] is True
    assert protected["release_approval_withheld_reason"]=="governance_incomplete"
    assert protected["all_governance_layers_executed"] is False
    assert protected["output_tokens"] == 3
    assert result==pristine
    assert protected is not result


@pytest.mark.parametrize("false_flag",[False,None,0,"false",[],{}])
def test_missing_or_invalid_full_governance_never_grants_approval(false_flag):
    result=synthetic_partial_result()
    result["all_governance_layers_executed"]=false_flag
    protected=ProjectExecutionWorker._truthful_completion_summary(result)
    assert protected["approved"] is False
    assert protected["readiness_score"] == 0.0
    assert protected["release_approval_withheld"] is True


@pytest.mark.parametrize("approved,score",[
    (True,1.0),(True,0.76),(True,100),(False,0.71),(None,0.0),
])
def test_partial_governance_always_sanitizes_inconsistent_approval(approved,score):
    result=synthetic_partial_result(approved=approved,score=score)
    changed=ProjectExecutionWorker._truthful_completion_summary(result)
    assert changed["approved"] is False
    assert changed["readiness_score"] == 0.0


def test_truly_governed_legacy_result_keeps_its_independent_approval():
    result={
        "approved":True,"readiness_score":0.93,
        "all_governance_layers_executed":True,
        "integration_foundation":False,
    }
    assert ProjectExecutionWorker._truthful_completion_summary(result) is result


def test_explicitly_full_governed_integration_remains_external_admission():
    result=synthetic_partial_result(approved=True,score=0.88)
    result["all_governance_layers_executed"]=True
    unchanged=ProjectExecutionWorker._truthful_completion_summary(result)
    assert unchanged is result
    assert unchanged["approved"] is True


def test_unmarked_legacy_runner_result_not_modified():
    result={"approved":True,"readiness_score":1.0,"workforce":[{"worker_id":"w"}]}
    assert ProjectExecutionWorker._truthful_completion_summary(result) is result


def test_integration_foundation_requires_exact_true_not_truthiness():
    for value in (0,1,"yes","true",None,False):
        result=synthetic_partial_result()
        result["integration_foundation"]=value
        if value is not True:
            assert ProjectExecutionWorker._truthful_completion_summary(result) is result



def test_real_four_tenant_ollama_routing_receipt_never_overclaims_governance():
    root=Path(__file__).resolve().parents[3]
    raw=root/"docs/project/receipts/FR09-20261025-4-REAL-VALIDATED-OLLAMA-ROUTES-RAW.json"
    manifest=root/"docs/project/receipts/FR09-20261025-4-REAL-ROUTES-GOVERNANCE-WITHHELD-AUDIT.json"
    proof=raw.read_bytes()
    assert hashlib.sha256(proof).hexdigest()==(
        "f5ab71f72a485d9bc53bdff5514cbcfeaa30b9eba54198b4f0677a2199938f5b"
    )
    data=json.loads(proof)
    lab=json.loads(manifest.read_text())
    assert data["sample_real_provider_generated_calls"]==4
    assert data["sample_real_durable_project_executions"]==4
    assert data["all_four_execution_approvals_safely_withheld"] is True
    assert data["all_four_statuses_rework_required"] is True
    assert data["all_four_readiness_scores_zero"] is True
    assert data["full_owner_governance_accepted"] is False
    assert data["injected_policy_resolver_instead_of_full_owner_policy"] is True
    assert data["uses_real_live_provider_invoker"] is True
    assert data["uses_real_durable_provider_route_store"] is True
    assert data["uses_real_redis_coordination"] is True
    assert data["total_model_output_tokens"]==12
    assert data["real_paid_provider_calls"]==0
    assert len(data["per_job"])==4
    assert len({entry["execution_ref_sha256"] for entry in data["per_job"]})==4
    assert len({entry["organization_ref_sha256"] for entry in data["per_job"]})==4
    assert all(entry["model"]=="gemma3:4b" and entry["model_output_tokens"]>0
               and entry["durable_claim_audits"]==1
               and entry["durable_completion_audits"]==1
               and entry["tenant_and_project_owner_verified"]
               for entry in data["per_job"])
    assert data["final_release_accepted"] is False
    assert lab["verified"] is True
    assert lab["original_production_container_identities_unchanged"] is True
    assert lab["remaining_isolated_containers"]==[]
