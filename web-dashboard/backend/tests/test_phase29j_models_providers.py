from app.core.ai_runtime import FINAL_SUPPORTED_PROVIDER_TYPES, AIRuntimeState, provider_models


def test_phase29j_supported_provider_types_are_final_contract():
    assert set(FINAL_SUPPORTED_PROVIDER_TYPES) == {"openai", "anthropic", "gemini", "openrouter", "ollama", "mistral", "cohere", "xai", "deepseek", "groq", "together", "fireworks", "huggingface", "azure_openai", "aws_bedrock"}


def test_model_catalog_is_truthful_and_provider_scoped():
    assert provider_models("openai")
    assert provider_models("ollama")[0]["local"] is True
    assert provider_models("does-not-exist") == []


def test_runtime_does_not_expose_raw_provider_key():
    runtime = AIRuntimeState()
    created = runtime.create_provider({"name": "Anthropic", "type": "anthropic", "api_key": "secret-value-1234", "base_url": None, "cost_per_1k_tokens": 0.0, "usage_limit": 0}, "org")
    assert created["api_key_hint"].endswith("1234")
    assert "secret-value-1234" not in repr(created)
