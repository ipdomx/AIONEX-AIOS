from app.api.v1.endpoints.final_integration import _available_api_routes
from app.core.integration_registry import IntegrationContract, IntegrationRegistry
from fastapi import Request
from main import app


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


def test_final_integration_discovers_lazy_included_routes():
    request = Request({"type": "http", "app": app})

    available_routes = _available_api_routes(request)

    assert {
        "/auth/me",
        "/projects",
        "/realtime/status",
        "/monitoring/health",
    } <= available_routes
