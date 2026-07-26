from app.core.integration_registry import IntegrationContract, IntegrationRegistry


def test_final_integration_registry_reports_missing_routes():
    registry = IntegrationRegistry()
    registry.register(IntegrationContract("identity", ("/auth/me", "/users")))
    result = registry.validate({"/auth/me"})
    assert result["valid"] is False
    assert result["missing_routes"] == {"identity": ["/users"]}


def test_final_integration_registry_accepts_complete_contracts():
    registry = IntegrationRegistry()
    registry.register(IntegrationContract("operations", ("/projects", "/tasks")))
    result = registry.validate({"/projects", "/tasks"})
    assert result["valid"] is True
    assert result["health"]["operations"] is True
