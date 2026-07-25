import asyncio

from aios.providers import DataSensitivity, ModelRequest, ModelResponse, MultiModelPlatform, NoEligibleProvider


async def fake_transport(request, model):
    return ModelResponse(provider="test", model=model, text=f"ok:{request.task}", input_tokens=10,
                         output_tokens=5, latency_ms=4.0, cost=0.001, confidence=0.9)


def test_default_registry_is_extensible_and_owner_controllable():
    platform = MultiModelPlatform()
    assert len(platform.registry.all()) >= 10
    platform.registry.disable("openai")
    assert not platform.registry.get("openai").enabled
    platform.registry.enable("openai")
    assert platform.registry.get("openai").enabled


def test_restricted_data_routes_only_to_local_provider():
    platform = MultiModelPlatform()
    request = ModelRequest(task="coding", prompt="secret", sensitivity=DataSensitivity.RESTRICTED)
    route = platform.router.select(request)
    assert route.provider == "ollama"


def test_project_policy_can_block_provider():
    platform = MultiModelPlatform()
    platform.policy.allowed_by_project["p"] = {"anthropic"}
    route = platform.router.select(ModelRequest(task="coding", prompt="x"), project="p")
    assert route.provider == "anthropic"


def test_budget_filters_expensive_routes():
    platform = MultiModelPlatform()
    platform.costs.set_limit("project:p", 0.0)
    platform.policy.allowed_by_project["p"] = {"openai", "anthropic", "gemini"}
    try:
        platform.router.select(ModelRequest(task="coding", prompt="x"), project="p", budget_scope="project:p")
    except NoEligibleProvider:
        pass
    else:
        raise AssertionError("expected budget to reject paid routes")


def test_generate_uses_configured_transport_and_records_metrics():
    platform = MultiModelPlatform({"openai": fake_transport})
    platform.policy.allowed_by_project["p"] = {"openai"}
    response = asyncio.run(platform.generate(ModelRequest(task="coding", prompt="x"), project="p"))
    assert response.text == "ok:coding"
    assert platform.metrics.get("openai").successes == 1


def test_health_check_marks_unconfigured_providers_degraded():
    states = asyncio.run(MultiModelPlatform().health_check())
    assert states["openai"] == "degraded"
    assert states["ollama"] == "degraded"
