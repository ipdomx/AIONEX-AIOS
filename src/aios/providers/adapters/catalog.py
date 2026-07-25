from __future__ import annotations

from .claude import ClaudeProvider
from .gemini import GeminiProvider
from .generic import GenericProvider
from .ollama import OllamaProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider
from ..base import BaseAIProvider, Transport
from ..models import ModelCapability


def _cap(provider: str, model: str, tasks: set[str], *, local: bool = False,
         tools: bool = True, vision: bool = False, audio: bool = False,
         quality: float = 0.8, latency: float = 0.7, privacy: float = 0.6,
         input_cost: float = 0.0, output_cost: float = 0.0,
         context: int = 128000) -> ModelCapability:
    return ModelCapability(
        provider=provider, model=model, tasks=frozenset(tasks),
        languages=frozenset({"ar", "en", "multilingual"}), supports_tools=tools,
        supports_vision=vision, supports_audio=audio, local=local,
        max_context_tokens=context, quality_score=quality,
        latency_score=latency, privacy_score=privacy,
        input_cost_per_million=input_cost, output_cost_per_million=output_cost,
    )


def default_providers(transports: dict[str, Transport] | None = None) -> tuple[BaseAIProvider, ...]:
    transports = transports or {}
    openai_caps = (_cap("openai", "default", {"coding", "reasoning", "research", "vision", "audio", "embedding", "image"}, vision=True, audio=True, quality=.93, input_cost=5, output_cost=15),)
    anthropic_caps = (_cap("anthropic", "default", {"coding", "reasoning", "review", "research", "vision"}, vision=True, quality=.94, input_cost=3, output_cost=15, context=200000),)
    gemini_caps = (_cap("gemini", "default", {"coding", "reasoning", "research", "vision", "audio", "files"}, vision=True, audio=True, quality=.9, input_cost=2, output_cost=8),)
    openrouter_caps = (_cap("openrouter", "default", {"coding", "reasoning", "research", "gateway"}, quality=.82, input_cost=1, output_cost=4),)
    ollama_caps = (_cap("ollama", "default", {"coding", "reasoning", "private", "embedding"}, local=True, quality=.75, latency=.55, privacy=1.0),)
    providers: list[BaseAIProvider] = [
        OpenAIProvider(openai_caps, transports.get("openai")),
        ClaudeProvider(anthropic_caps, transports.get("anthropic")),
        GeminiProvider(gemini_caps, transports.get("gemini")),
        OpenRouterProvider(openrouter_caps, transports.get("openrouter")),
        OllamaProvider(ollama_caps, transports.get("ollama")),
    ]
    generic_specs = {
        "mistral": (_cap("mistral", "default", {"coding", "reasoning"}, quality=.82, input_cost=2, output_cost=6),),
        "cohere": (_cap("cohere", "default", {"research", "retrieval", "reasoning"}, quality=.79, input_cost=2, output_cost=5),),
        "xai": (_cap("xai", "default", {"reasoning", "research", "coding"}, quality=.84, input_cost=3, output_cost=12),),
        "deepseek": (_cap("deepseek", "default", {"coding", "reasoning"}, quality=.86, input_cost=1, output_cost=2),),
        "groq": (_cap("groq", "default", {"coding", "reasoning"}, quality=.78, latency=.97, input_cost=.5, output_cost=.8),),
        "together": (_cap("together", "default", {"coding", "reasoning", "research"}, quality=.78, input_cost=.6, output_cost=.9),),
        "fireworks": (_cap("fireworks", "default", {"coding", "reasoning"}, quality=.78, latency=.88, input_cost=.6, output_cost=.9),),
        "huggingface": (_cap("huggingface", "default", {"coding", "research", "embedding"}, quality=.72, input_cost=.4, output_cost=.6),),
        "azure_openai": (_cap("azure_openai", "default", {"coding", "reasoning", "enterprise"}, quality=.91, privacy=.85, input_cost=5, output_cost=15),),
        "aws_bedrock": (_cap("aws_bedrock", "default", {"coding", "reasoning", "enterprise"}, quality=.87, privacy=.85, input_cost=4, output_cost=12),),
    }
    providers.extend(GenericProvider(name, caps, transports.get(name)) for name, caps in generic_specs.items())
    return tuple(providers)
