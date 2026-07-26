from aios.api_experience import (
    APIContract,
    APIEndpoint,
    APIExperiencePlatform,
    APIMethod,
    APIResponse,
    RateLimitPolicy,
)


def test_api_experience_end_to_end() -> None:
    platform = APIExperiencePlatform.build_default()

    def handler(payload: dict[str, object], context: dict[str, object]) -> APIResponse:
        return APIResponse(
            status_code=200,
            body={
                "echo": payload,
                "principal_id": context["principal_id"],
            },
        )

    contract = APIContract(
        contract_id="projects.read",
        version="v1",
        method=APIMethod.POST,
        path="/projects/query",
        required_capabilities=frozenset({"projects:read"}),
    )
    platform.registry.register(APIEndpoint(contract=contract, handler=handler))
    platform.gateway.set_policy(
        "projects.read",
        RateLimitPolicy(policy_id="projects.read", limit=2, window_seconds=60),
    )

    context = platform.middleware.build_context(
        principal_id="user-1",
        correlation_id="corr-1",
        organization_id="org-1",
        capabilities={"projects:read"},
    )

    response = platform.gateway.dispatch(
        "v1",
        "POST",
        "/projects/query",
        {"status": "active"},
        context,
    )

    assert response.status_code == 200
    assert response.body["principal_id"] == "user-1"
    assert response.headers["X-Correlation-ID"] == "corr-1"
    assert platform.validate()["ready"] is True


def test_access_and_rate_limit_controls() -> None:
    platform = APIExperiencePlatform.build_default()
    contract = APIContract(
        contract_id="admin.health",
        version="v1",
        method=APIMethod.GET,
        path="/admin/health",
        required_capabilities=frozenset({"admin:read"}),
    )
    platform.registry.register(
        APIEndpoint(
            contract=contract,
            handler=lambda payload, context: APIResponse(status_code=200, body={"ok": True}),
        )
    )
    platform.gateway.set_policy(
        "admin.health",
        RateLimitPolicy(policy_id="admin.health", limit=1, window_seconds=60),
    )

    denied_context = platform.middleware.build_context("user-2")
    denied = platform.gateway.dispatch("v1", "GET", "/admin/health", {}, denied_context)
    assert denied.status_code == 403

    allowed_context = platform.middleware.build_context("admin-1", capabilities={"admin:read"})
    first = platform.gateway.dispatch("v1", "GET", "/admin/health", {}, allowed_context)
    second = platform.gateway.dispatch("v1", "GET", "/admin/health", {}, allowed_context)
    assert first.status_code == 200
    assert second.status_code == 429
