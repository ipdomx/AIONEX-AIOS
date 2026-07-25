from __future__ import annotations

from typing import Any

from .provider import ImplementedProvider, RawTransport, StreamTransport
from ..base import Transport
from ..models import ModelCapability, ModelRequest


class OllamaProvider(ImplementedProvider):
    def __init__(self, capabilities: tuple[ModelCapability, ...], transport: Transport | None = None,
                 *, raw_transport: RawTransport | None = None, stream_transport: StreamTransport | None = None) -> None:
        super().__init__("ollama", capabilities, transport, raw_transport=raw_transport,
                         stream_transport=stream_transport, requests_per_minute=1000, concurrent_requests=4)

    def build_payload(self, request: ModelRequest, model: str) -> dict[str, Any]:
        payload = super().build_payload(request, model)
        payload["stream"] = False
        payload["options"] = {"temperature": request.temperature, "num_predict": request.max_tokens}
        payload.pop("max_tokens", None)
        payload.pop("temperature", None)
        return payload

    async def list_models(self) -> tuple[dict[str, Any], ...]:
        if self._raw_transport is None:
            return ()
        result = await self._raw_transport({"operation": "list_models"})
        return tuple(result.get("models", ()))

    async def pull_model(self, model: str) -> dict[str, Any]:
        if self._raw_transport is None:
            raise RuntimeError("ollama raw transport is not configured")
        return await self._raw_transport({"operation": "pull_model", "model": model})

    async def embeddings(self, inputs: list[str], model: str) -> dict[str, Any]:
        if self._raw_transport is None:
            raise RuntimeError("ollama raw transport is not configured")
        return await self._raw_transport({"operation": "embeddings", "model": model, "input": inputs})
