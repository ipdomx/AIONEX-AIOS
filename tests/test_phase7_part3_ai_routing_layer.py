import asyncio

from aios.providers import (AIRoutingLayer, DataSensitivity, ExecutionMode, ModelRequest,
                            ModelResponse, MultiModelPlatform, OptimizationMode, RoutingPolicy)


def transport(name, text, confidence, cost=0.01, latency=10):
    async def call(request, model):
        return ModelResponse(provider=name, model=model, text=text, input_tokens=5,
                             output_tokens=3, confidence=confidence, cost=cost,
                             latency_ms=latency)
    return call


def test_cost_speed_quality_and_privacy_optimization():
    platform = MultiModelPlatform({
        "openai": transport("openai", "a", .9, .03, 30),
        "anthropic": transport("anthropic", "b", .95, .02, 20),
        "ollama": transport("ollama", "c", .7, 0, 5),
    })
    layer = AIRoutingLayer(platform)
    request = ModelRequest(task="coding", prompt="x")
    assert layer.rank(request, RoutingPolicy(optimization=OptimizationMode.COST))[0].provider == "ollama"
    assert layer.rank(request, RoutingPolicy(optimization=OptimizationMode.PRIVACY))[0].provider == "ollama"
    restricted = ModelRequest(task="coding", prompt="x", sensitivity=DataSensitivity.RESTRICTED)
    assert layer.rank(restricted)[0].provider == "ollama"


def test_multi_model_best_result_and_metrics():
    platform = MultiModelPlatform({"openai": transport("openai", "A", .8),
                                   "anthropic": transport("anthropic", "B", .95)})
    platform.policy.allowed_by_project["p"] = {"openai", "anthropic"}
    layer = AIRoutingLayer(platform)
    policy = RoutingPolicy(execution=ExecutionMode.PARALLEL, max_models=2)
    result = asyncio.run(layer.execute(ModelRequest(task="coding", prompt="x"), policy, project="p"))
    assert result.selected.text == "B"
    assert len(result.candidates) == 2
    assert layer.metrics.daily_report()["requests"] == 2


def test_voting_and_consensus():
    platform = MultiModelPlatform({"openai": transport("openai", "same", .8),
                                   "anthropic": transport("anthropic", "same", .9),
                                   "gemini": transport("gemini", "other", .95)})
    platform.policy.allowed_by_project["p"] = {"openai", "anthropic", "gemini"}
    layer = AIRoutingLayer(platform)
    request = ModelRequest(task="coding", prompt="x")
    vote = asyncio.run(layer.execute(request, RoutingPolicy(execution=ExecutionMode.VOTE, max_models=3), project="p"))
    assert vote.selected.text == "same"
    consensus = asyncio.run(layer.execute(request, RoutingPolicy(execution=ExecutionMode.CONSENSUS, max_models=3), project="p"))
    assert consensus.selected.metadata["consensus_size"] == 3


def test_failover_uses_next_provider():
    async def broken(request, model):
        raise ConnectionError("down")
    platform = MultiModelPlatform({"openai": broken, "anthropic": transport("anthropic", "ok", .9)})
    platform.policy.allowed_by_project["p"] = {"openai", "anthropic"}
    layer = AIRoutingLayer(platform)
    policy = RoutingPolicy(provider_priority=("openai", "anthropic"), allow_failover=True)
    result = asyncio.run(layer.execute(ModelRequest(task="coding", prompt="x"), policy, project="p"))
    assert result.selected.text == "ok"
    assert len(result.candidates) == 2
    assert layer.health.snapshot()["openai"]["state"] == "unavailable"


def test_offline_mode_filters_remote_providers():
    layer = AIRoutingLayer(MultiModelPlatform({"ollama": transport("ollama", "local", .7)}))
    result = asyncio.run(layer.execute(ModelRequest(task="coding", prompt="x"),
                                       RoutingPolicy(offline_only=True)))
    assert result.selected.provider == "ollama"
