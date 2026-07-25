from __future__ import annotations

from typing import Any

from .provider import ImplementedProvider, RawTransport, StreamTransport
from ..base import Transport
from ..models import ModelCapability, ModelRequest


class OpenRouterProvider(ImplementedProvider):
    def __init__(self, capabilities: tuple[ModelCapability, ...], transport: Transport | None = None,
                 *, raw_transport: RawTransport | None = None, stream_transport: StreamTransport | None = None) -> None:
        super().__init__("openrouter", capabilities, transport, raw_transport=raw_transport,
                         stream_transport=stream_transport, requests_per_minute=300)
        self._discovered_models: tuple[dict[str, Any], ...] = ()

    def build_payload(self, request: ModelRequest, model: str) -> dict[str, Any]:
        payload = super().build_payload(request, model)
        payload["provider"] = {
            "order": request.metadata.get("provider_priority", []),
            "allow_fallbacks": request.metadata.get("allow_fallbacks", True),
        }
        return payload

    async def discover_models(self) -> tuple[dict[str, Any], ...]:
        if self._raw_transport is None:
            return self._discovered_models
        payload = await self._raw_transport({"operation": "models"})
        models = payload.get("models", payload.get("data", []))
        self._discovered_models = tuple(dict(item) for item in models)
        return self._discovered_models

    @staticmethod
    def select_provider(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        eligible = [item for item in candidates if item.get("available", True)]
        if not eligible:
            return None
        return min(eligible, key=lambda item: (item.get("priority", 100), item.get("cost", float("inf"))))
