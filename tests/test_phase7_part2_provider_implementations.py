import asyncio

from aios.providers import ModelRequest, ModelResponse, MultiModelPlatform
from aios.providers.adapters import ClaudeProvider, GeminiProvider, OllamaProvider, OpenAIProvider, OpenRouterProvider
from aios.providers.adapters.catalog import default_providers
from aios.providers.shared import RetryManager, RetryPolicy, TokenCounter


def provider(name):
    return {item.name: item for item in default_providers()}[name]


def test_catalog_uses_concrete_provider_implementations():
    assert isinstance(provider("openai"), OpenAIProvider)
    assert isinstance(provider("anthropic"), ClaudeProvider)
    assert isinstance(provider("gemini"), GeminiProvider)
    assert isinstance(provider("openrouter"), OpenRouterProvider)
    assert isinstance(provider("ollama"), OllamaProvider)


def test_provider_payloads_are_vendor_specific():
    request = ModelRequest(task="coding", prompt="hello", system_prompt="safe", metadata={"tools": [{"name": "x"}]})
    assert "input" in provider("openai").build_payload(request, "m")
    assert provider("anthropic").build_payload(request, "m")["system"] == "safe"
    assert "contents" in provider("gemini").build_payload(request, "m")
    assert "provider" in provider("openrouter").build_payload(request, "m")
    assert provider("ollama").build_payload(request, "m")["stream"] is False


def test_retry_manager_retries_transient_failures():
    calls = {"count": 0}

    async def operation():
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("transient")
        return "ok"

    result = asyncio.run(RetryManager(RetryPolicy(max_attempts=3, base_delay=0)).run(operation))
    assert result == "ok"
    assert calls["count"] == 3


def test_token_counter_is_deterministic():
    counter = TokenCounter()
    assert counter.estimate_request("abcd", "abcd") == 2


def test_stream_falls_back_to_complete_response():
    async def transport(request, model):
        return ModelResponse(provider="openai", model=model, text="complete")

    p = OpenAIProvider(provider("openai").capabilities(), transport)

    async def collect():
        return [chunk async for chunk in p.stream(ModelRequest(task="coding", prompt="x"), "default")]

    assert asyncio.run(collect()) == ["complete"]


def test_platform_remains_backward_compatible():
    async def transport(request, model):
        return ModelResponse(provider="openai", model=model, text="ok", cost=0.01)

    platform = MultiModelPlatform({"openai": transport})
    platform.policy.allowed_by_project["p"] = {"openai"}
    result = asyncio.run(platform.generate(ModelRequest(task="coding", prompt="x"), project="p"))
    assert result.text == "ok"
