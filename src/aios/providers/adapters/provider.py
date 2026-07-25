from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from ..base import BaseAIProvider, Transport
from ..models import ModelCapability, ModelRequest, ModelResponse, ProviderState
from ..shared import AsyncRateLimiter, RequestNormalizer, ResponseNormalizer, RetryManager, RetryPolicy, TokenCounter

RawTransport = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
StreamTransport = Callable[[dict[str, Any]], AsyncIterator[dict[str, Any] | str]]


class ImplementedProvider(BaseAIProvider):
    def __init__(self, name: str, capabilities: tuple[ModelCapability, ...], transport: Transport | None = None,
                 *, raw_transport: RawTransport | None = None, stream_transport: StreamTransport | None = None,
                 requests_per_minute: int = 60, concurrent_requests: int = 8,
                 retry_policy: RetryPolicy | None = None) -> None:
        super().__init__(name, capabilities, transport)
        self._raw_transport = raw_transport
        self._stream_transport = stream_transport
        self.retry = RetryManager(retry_policy)
        self.rate_limiter = AsyncRateLimiter(requests_per_minute, concurrent_requests)
        self.tokens = TokenCounter()

    async def _probe(self) -> ProviderState:
        return ProviderState.HEALTHY if (self._transport or self._raw_transport) else ProviderState.DEGRADED

    def build_payload(self, request: ModelRequest, model: str) -> dict[str, Any]:
        return RequestNormalizer.common(request, model)

    async def generate(self, request: ModelRequest, model: str) -> ModelResponse:
        if self._transport is not None:
            async with self.rate_limiter:
                return await self.retry.run(lambda: super(ImplementedProvider, self).generate(request, model))
        if self._raw_transport is None:
            return await super().generate(request, model)
        self.capability(model)
        payload = self.build_payload(request, model)
        async with self.rate_limiter:
            raw = await self.retry.run(lambda: self._raw_transport(payload))
        return ResponseNormalizer.from_mapping(self.name, model, raw)

    async def stream(self, request: ModelRequest, model: str) -> AsyncIterator[str]:
        if self._stream_transport is None:
            response = await self.generate(request, model)
            if response.text:
                yield response.text
            return
        payload = self.build_payload(request, model)
        async with self.rate_limiter:
            async for chunk in self._stream_transport(payload):
                if isinstance(chunk, str):
                    yield chunk
                else:
                    text = chunk.get("text") or chunk.get("delta") or ""
                    if text:
                        yield str(text)

    def estimate_tokens(self, request: ModelRequest) -> int:
        return self.tokens.estimate_request(request.prompt, request.system_prompt)
