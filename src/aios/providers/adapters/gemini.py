from __future__ import annotations

from typing import Any

from .provider import ImplementedProvider, RawTransport, StreamTransport
from ..base import Transport
from ..models import ModelCapability, ModelRequest


class GeminiProvider(ImplementedProvider):
    def __init__(self, capabilities: tuple[ModelCapability, ...], transport: Transport | None = None,
                 *, raw_transport: RawTransport | None = None, stream_transport: StreamTransport | None = None) -> None:
        super().__init__("gemini", capabilities, transport, raw_transport=raw_transport,
                         stream_transport=stream_transport, requests_per_minute=300)

    def build_payload(self, request: ModelRequest, model: str) -> dict[str, Any]:
        return {
            "model": model,
            "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
            "system_instruction": {"parts": [{"text": request.system_prompt}]} if request.system_prompt else None,
            "generation_config": {"max_output_tokens": request.max_tokens, "temperature": request.temperature},
            "tools": request.metadata.get("tools", []),
            "safety_settings": request.metadata.get("safety_settings", []),
            "files": request.metadata.get("files", []),
        }
