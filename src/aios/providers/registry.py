from __future__ import annotations

from .base import BaseAIProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, BaseAIProvider] = {}

    def register(self, provider: BaseAIProvider, *, replace: bool = False) -> None:
        if provider.name in self._providers and not replace:
            raise ValueError(f"provider already registered: {provider.name}")
        self._providers[provider.name] = provider

    def unregister(self, name: str) -> None:
        self._providers.pop(name, None)

    def get(self, name: str) -> BaseAIProvider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"unknown provider: {name}") from exc

    def all(self) -> tuple[BaseAIProvider, ...]:
        return tuple(self._providers[name] for name in sorted(self._providers))

    def enable(self, name: str) -> None:
        self.get(name).enable()

    def disable(self, name: str) -> None:
        self.get(name).disable()
