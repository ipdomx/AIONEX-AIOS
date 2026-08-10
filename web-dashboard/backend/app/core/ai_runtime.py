"""Shared AI realtime transport and provider capability catalogue.

Durable provider, agent, and execution state lives in PostgreSQL through
``app.services.ai_runtime_service``. Only websocket connection membership remains
process-local because it is transport state rather than business state.
"""
from __future__ import annotations

import asyncio
from typing import Any


class AIRealtimeHub:
    def __init__(self) -> None:
        self._clients: dict[str, set[Any]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, organization_id: str, websocket: Any) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.setdefault(organization_id, set()).add(websocket)

    async def disconnect(self, organization_id: str, websocket: Any) -> None:
        async with self._lock:
            clients = self._clients.get(organization_id)
            if clients:
                clients.discard(websocket)
                if not clients:
                    self._clients.pop(organization_id, None)

    async def publish(self, organization_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._clients.get(organization_id, set()))
        stale: list[Any] = []
        for client in clients:
            try:
                await client.send_json(event)
            except Exception:
                stale.append(client)
        for client in stale:
            await self.disconnect(organization_id, client)

    def connected_count(self, organization_id: str | None = None) -> int:
        if organization_id:
            return len(self._clients.get(organization_id, set()))
        return sum(len(clients) for clients in self._clients.values())


ai_realtime_hub = AIRealtimeHub()

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
