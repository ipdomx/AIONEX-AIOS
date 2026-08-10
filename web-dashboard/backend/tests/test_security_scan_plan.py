import pytest
from types import SimpleNamespace
from app.services.security_scanning import build_tool_plan, _profile_mode


def test_elite_clone_plan_contains_deep_validation_engines():
    plan = build_tool_plan(
        "elite", source_available=True, execution_mode="intrusive_clone"
    )
    ids = {item["id"] for item in plan}
    assert {
        "zap-active",
        "restler",
        "sqlmap",
        "xsstrike",
        "commix",
        "semgrep",
        "trivy",
        "syft",
    } <= ids


def test_advanced_requires_clone_when_policy_says_so():
    target = SimpleNamespace(
        active_scan_allowed=True, target_metadata={"environment": "production"}
    )
    with pytest.raises(PermissionError):
        _profile_mode("advanced", target, {"deep_validation_requires_clone": True})
    clone = SimpleNamespace(
        active_scan_allowed=True, target_metadata={"environment": "security_clone"}
    )
    assert (
        _profile_mode("advanced", clone, {"deep_validation_requires_clone": True})
        == "intrusive_clone"
    )
