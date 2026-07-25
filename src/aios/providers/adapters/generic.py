from __future__ import annotations

from ..base import BaseAIProvider, Transport
from ..models import ModelCapability, ProviderState


class GenericProvider(BaseAIProvider):
    def __init__(self, name: str, capabilities: tuple[ModelCapability, ...], transport: Transport | None = None):
        super().__init__(name, capabilities, transport)

    async def _probe(self) -> ProviderState:
        return ProviderState.HEALTHY if self._transport is not None else ProviderState.DEGRADED
