"""Shared AI provider capability catalogue.

Durable provider, agent, and execution state lives in PostgreSQL through
``app.services.ai_runtime_service``. Realtime websocket delivery is owned by
``app.realtime.runtime`` and uses the distributed Redis backplane.
"""
from __future__ import annotations

FINAL_SUPPORTED_PROVIDER_TYPES = (
    "openai",
    "anthropic",
    "gemini",
    "openrouter",
    "ollama",
    "mistral",
    "cohere",
    "xai",
    "deepseek",
    "groq",
    "together",
    "fireworks",
    "huggingface",
    "azure_openai",
    "aws_bedrock",
    "tripo3d",
    "meshy",
)


def provider_models(provider_type: str) -> list[dict[str, object]]:
    from aios.providers.adapters.catalog import default_providers

    provider = next(
        (item for item in default_providers() if item.name == provider_type), None
    )
    if provider is None:
        return []
    return [
        {
            "provider": cap.provider,
            "model": cap.model,
            "tasks": sorted(cap.tasks),
            "languages": sorted(cap.languages),
            "supports_tools": cap.supports_tools,
            "supports_vision": cap.supports_vision,
            "supports_audio": cap.supports_audio,
            "local": cap.local,
            "max_context_tokens": cap.max_context_tokens,
            "quality_score": cap.quality_score,
            "latency_score": cap.latency_score,
            "privacy_score": cap.privacy_score,
            "input_cost_per_million": cap.input_cost_per_million,
            "output_cost_per_million": cap.output_cost_per_million,
        }
        for cap in provider.capabilities()
    ]
