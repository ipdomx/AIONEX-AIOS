from __future__ import annotations

from typing import Any

from .provider import ImplementedProvider, RawTransport, StreamTransport
from ..base import Transport
from ..models import ModelCapability, ModelRequest


class OpenAIProvider(ImplementedProvider):
    def __init__(self, capabilities: tuple[ModelCapability, ...], transport: Transport | None = None,
                 *, raw_transport: RawTransport | None = None, stream_transport: StreamTransport | None = None) -> None:
        super().__init__("openai", capabilities, transport, raw_transport=raw_transport,
                         stream_transport=stream_transport, requests_per_minute=500)

    def build_payload(self, request: ModelRequest, model: str) -> dict[str, Any]:
        payload = super().build_payload(request, model)
        payload["input"] = payload.pop("messages")
        payload["max_output_tokens"] = payload.pop("max_tokens")
        payload["tools"] = request.metadata.get("tools", [])
        payload["response_format"] = request.metadata.get("response_format")
        return {k: v for k, v in payload.items() if v not in (None, [], {})}

    async def embeddings(self, inputs: list[str], model: str = "text-embedding-3-small") -> dict[str, Any]:
        if self._raw_transport is None:
            raise RuntimeError("openai raw transport is not configured")
        return await self._raw_transport({"operation": "embeddings", "model": model, "input": inputs})

    async def image(self, prompt: str, model: str = "gpt-image-2") -> dict[str, Any]:
        if self._raw_transport is None:
            raise RuntimeError("openai raw transport is not configured")
        return await self._raw_transport({"operation": "image", "model": model, "prompt": prompt})

    async def audio(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._raw_transport is None:
            raise RuntimeError("openai raw transport is not configured")
        return await self._raw_transport({"operation": f"audio:{operation}", **payload})
