from __future__ import annotations

from .base import ModelProvider, ModelResponse


class UnconfiguredLocalProvider(ModelProvider):
    """Truthful local-model activation boundary.

    This provider never fabricates model output. It exists only so callers get a
    deterministic, actionable failure until a real local runtime such as Ollama
    is configured through the supported provider platform.
    """

    name = "local-unconfigured"

    def __init__(self, model: str = "unconfigured"):
        self.model = model

    def generate(self, prompt: str, system: str | None = None) -> ModelResponse:
        raise RuntimeError(
            "No local model runtime is configured. Configure Ollama or an OpenAI-compatible local endpoint before execution."
        )
