from app.services.security_deep_validation import (
    authorization_matrix,
    build_scenario_plan,
)


def test_deep_validation_is_clone_only():
    result = build_scenario_plan(environment="production", available_roles=["user"])
    assert result["admitted"] is False
    assert result["scenarios"] == []


def test_clone_plan_exposes_missing_test_fixtures_instead_of_faking_success():
    result = build_scenario_plan(
        environment="security_clone", available_roles=["user", "admin"]
    )
    assert result["admitted"] is True
    object_matrix = next(
        item for item in result["scenarios"] if item["id"] == "authz-object-matrix"
    )
    assert object_matrix["ready"] is False
    assert "user_a" in object_matrix["missing_roles"]


def test_authorization_matrix_never_invents_expected_permission_decisions():
    matrix = authorization_matrix(["user", "admin"], ["project"], ["read", "delete"])
    assert len(matrix) == 4
    assert {row["expected"] for row in matrix} == {"policy_required"}
