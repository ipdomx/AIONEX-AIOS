from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from .models import ModelCapability, ModelRequest, ModelResponse, ProviderState

Transport = Callable[[ModelRequest, str], Awaitable[ModelResponse]]


class BaseAIProvider(ABC):
    def __init__(self, name: str, capabilities: tuple[ModelCapability, ...], transport: Transport | None = None):
        self.name = name
        self._capabilities = capabilities
        self._transport = transport
        self._enabled = True
        self._state = ProviderState.UNKNOWN

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def state(self) -> ProviderState:
        return ProviderState.DISABLED if not self._enabled else self._state

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False

    def capabilities(self) -> tuple[ModelCapability, ...]:
        return self._capabilities

    def capability(self, model: str) -> ModelCapability:
        for item in self._capabilities:
            if item.model == model:
                return item
        raise KeyError(f"unknown model {self.name}/{model}")

    async def health_check(self) -> ProviderState:
        if not self._enabled:
            return ProviderState.DISABLED
        self._state = await self._probe()
        return self._state

    async def generate(self, request: ModelRequest, model: str) -> ModelResponse:
        if not self._enabled:
            raise RuntimeError(f"provider {self.name} is disabled")
        self.capability(model)
        if self._transport is None:
            raise RuntimeError(f"provider {self.name} has no configured transport")
        return await self._transport(request, model)

    @abstractmethod
    async def _probe(self) -> ProviderState:
        raise NotImplementedError
