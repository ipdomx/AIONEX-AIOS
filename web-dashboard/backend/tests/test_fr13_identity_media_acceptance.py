from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/fr13_identity_media_acceptance_matrix.json"

EXPECTED_OPERATIONS = {
    "voice_clone",
    "voice_transform",
    "face_reenactment",
    "face_swap",
    "talking_head",
    "lip_sync",
    "avatar_generation",
}
EXPECTED_READY = {
    "voice_clone",
    "face_reenactment",
    "talking_head",
    "lip_sync",
    "avatar_generation",
}
EXPECTED_PENDING = {"voice_transform", "face_swap"}


def _matrix() -> dict:
    return json.loads(FIXTURE.read_text())


def _literal_assignment(relative: str, name: str):
    tree = ast.parse((ROOT / relative).read_text())
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in {"frozenset", "set", "tuple", "list"}
            and len(value.args) == 1
        ):
            value = value.args[0]
        return ast.literal_eval(value)
    raise AssertionError(f"{name} not found in {relative}")


def test_matrix_is_exactly_seven_rows_and_does_not_bulk_promote_pending_operations():
    matrix = _matrix()
    rows = {row["operation"]: row for row in matrix["operations"]}

    assert set(rows) == EXPECTED_OPERATIONS
    assert matrix["dependency"] == {
        "batch": "FR-12",
        "accepted": False,
        "effect_on_fr13": "integration_live_final_closure_gated",
    }
    assert {op for op, row in rows.items() if row["source_runtime_state"] == "ready"} == EXPECTED_READY
    assert {op for op, row in rows.items() if row["source_runtime_state"] == "pending"} == EXPECTED_PENDING
    assert all(rows[op]["independent_acceptance"] == "pending" for op in EXPECTED_PENDING)
    assert all(rows[op]["independent_acceptance"] != "final" for op in EXPECTED_OPERATIONS)


def test_matrix_runtime_truth_matches_current_access_and_provider_model_maps():
    rows = {row["operation"]: row for row in _matrix()["operations"]}

    access_operations = tuple(
        _literal_assignment(
            "web-dashboard/backend/app/services/identity_media_access.py", "OPERATIONS"
        )
    )
    runtime_ready = set(
        _literal_assignment(
            "web-dashboard/backend/app/services/identity_media_access.py",
            "RUNTIME_READY_OPERATIONS",
        )
    )
    endpoint_models = _literal_assignment(
        "web-dashboard/backend/app/api/v1/endpoints/identity_media.py",
        "_RUNTIME_MODELS",
    )
    provider_models = _literal_assignment(
        "web-dashboard/backend/app/services/identity_media_replicate.py",
        "_MODEL_BY_OPERATION",
    )
    policy_operations = set(
        _literal_assignment("src/aios/phase36_identity_media.py", "_ALLOWED_OPERATIONS")
    )

    assert set(access_operations) == EXPECTED_OPERATIONS
    assert policy_operations == EXPECTED_OPERATIONS
    assert runtime_ready == EXPECTED_READY
    assert set(endpoint_models) == EXPECTED_READY
    assert set(provider_models) == EXPECTED_READY
    assert endpoint_models == provider_models
    for operation in EXPECTED_READY:
        assert rows[operation]["provider_model"] == provider_models[operation]
    for operation in EXPECTED_PENDING:
        assert rows[operation]["provider_model"] is None
        assert operation not in endpoint_models
        assert operation not in provider_models


def test_each_row_binds_rights_owner_revocation_and_synthetic_disclosure_expectations():
    matrix = _matrix()
    assert len(matrix["operations"]) == 7
    for row in matrix["operations"]:
        assert row["rights_owner_revocation_required"] is True
        assert row["synthetic_media_disclosure_required"] is True

    policy_source = (ROOT / "src/aios/phase36_identity_media.py").read_text()
    access_source = (
        ROOT / "web-dashboard/backend/app/services/identity_media_access.py"
    ).read_text()
    endpoint_source = (
        ROOT / "web-dashboard/backend/app/api/v1/endpoints/identity_media.py"
    ).read_text()
    revocation_source = (
        ROOT / "web-dashboard/backend/tests/test_phase36_identity_media_revocation.py"
    ).read_text()

    assert "synthetic_media_disclosure_accepted" in policy_source
    assert "synthetic media disclosure must be accepted" in policy_source
    assert '"real_person_owner_approval_required": True' in access_source
    assert '"owner_grant_is_legal_license": False' in access_source
    assert "Licensed public-figure execution is pending a licensed-catalog runtime" in endpoint_source
    assert "test_revoked_queued_execution_does_not_submit_to_provider" in revocation_source
    assert "test_revoked_completed_output_cannot_be_downloaded" in revocation_source
    assert "test_revocation_during_input_preflight_prevents_primary_submission" in revocation_source
    assert "test_revocation_during_output_read_prevents_delivery" in revocation_source


def test_cost_authorization_ceiling_is_never_promoted_to_actual_cost():
    matrix = _matrix()
    assert matrix["cost_truth"]["authorized_ceiling_is_invoice"] is False
    assert "unknown/null" in matrix["cost_truth"]["actual_cost_rule"]
    assert "never a billed or actual cost" in matrix["cost_truth"]["cap_rule"]

    runtime_source = (
        ROOT / "web-dashboard/backend/app/services/identity_media_runtime.py"
    ).read_text()
    assert '"max_cost_authorization_usd": row.max_cost_usd' in runtime_source
    assert '"actual_cost_usd": row.actual_cost_usd' in runtime_source
    assert "actual_cost_usd=None" in runtime_source
    assert "actual_cost_usd > row.max_cost_usd" in runtime_source
    assert "row.actual_cost_usd = actual_cost_usd" in runtime_source
