import pytest
from aios.phase29j import ActivationState, FinalProviderRegistry, ProviderContract, SUPPORTED_PROVIDERS


def test_supported_provider_contract_is_explicit_and_complete():
    expected = {"openai", "anthropic", "gemini", "openrouter", "ollama", "mistral", "cohere", "xai", "deepseek", "groq", "together", "fireworks", "huggingface", "azure_openai", "aws_bedrock"}
    assert set(SUPPORTED_PROVIDERS) == expected


def test_activation_is_truthful_and_model_discovery_is_gated():
    reg = FinalProviderRegistry()
    reg.register(ProviderContract("openai", credential_ref="vault://openai", models=("gpt-default",), capabilities=frozenset({"text", "tools", "streaming", "structured_output", "embeddings", "image", "audio"})))
    assert reg.discover_models("openai") == ()
    reg.activate("openai")
    assert reg.providers["openai"].state is ActivationState.ACTIVE
    assert reg.discover_models("openai") == ("gpt-default",)


def test_missing_credentials_never_report_active():
    reg = FinalProviderRegistry(); reg.register(ProviderContract("anthropic", enabled=True, capabilities=frozenset({"text"})))
    assert reg.providers["anthropic"].state is ActivationState.UNCONFIGURED
    with pytest.raises(RuntimeError): reg.activate("anthropic")


def test_local_and_cloud_routing_no_fallback_and_fallback_modes():
    reg = FinalProviderRegistry()
    reg.register(ProviderContract("ollama", local=True, enabled=True, models=("local",), capabilities=frozenset({"text", "embeddings"})))
    reg.register(ProviderContract("openai", credential_ref="vault://openai", enabled=True, models=("cloud",), capabilities=frozenset({"text", "image"})))
    assert reg.select(capability="text", preferred=("ollama",)).provider_id == "ollama"
    reg.disable("ollama")
    with pytest.raises(RuntimeError): reg.select(capability="text", preferred=("ollama",), allow_fallback=False)
    assert reg.select(capability="text", preferred=("ollama",), allow_fallback=True).provider_id == "openai"


def test_inventory_exposes_every_provider_without_secrets():
    reg = FinalProviderRegistry(); reg.register(ProviderContract("openai", credential_ref="vault://secret-ref", daily_budget=12.5, max_requests_per_minute=100))
    rows = reg.inventory(); assert len(rows) == len(SUPPORTED_PROVIDERS)
    text = repr(rows); assert "vault://secret-ref" not in text
