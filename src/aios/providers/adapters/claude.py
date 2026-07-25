from __future__ import annotations

from typing import Any

from .provider import ImplementedProvider, RawTransport, StreamTransport
from ..base import Transport
from ..models import ModelCapability, ModelRequest


class ClaudeProvider(ImplementedProvider):
    def __init__(self, capabilities: tuple[ModelCapability, ...], transport: Transport | None = None,
                 *, raw_transport: RawTransport | None = None, stream_transport: StreamTransport | None = None) -> None:
        super().__init__("anthropic", capabilities, transport, raw_transport=raw_transport,
                         stream_transport=stream_transport, requests_per_minute=200)

    def build_payload(self, request: ModelRequest, model: str) -> dict[str, Any]:
        payload = super().build_payload(request, model)
        messages = payload["messages"]
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        payload["messages"] = [m for m in messages if m["role"] != "system"]
        payload["system"] = system
        payload["tools"] = request.metadata.get("tools", [])
        if request.metadata.get("thinking"):
            payload["thinking"] = request.metadata["thinking"]
        return {k: v for k, v in payload.items() if v not in (None, [], {}, "")}
