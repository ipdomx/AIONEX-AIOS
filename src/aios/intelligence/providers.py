from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Any


class ModelProvider(Protocol):
    name: str
    capabilities: set[str]

    def generate(self, prompt: str, *, system: str = '') -> Any: ...


@dataclass(slots=True, frozen=True)
class ProviderSelection:
    provider: ModelProvider
    score: float
    reasons: tuple[str, ...]


class ProviderRegistry:
    """Keeps AIOS independent from any model vendor."""

    def __init__(self) -> None:
        self._providers: dict[str, ModelProvider] = {}

    def register(self, provider: ModelProvider) -> None:
        self._providers[provider.name] = provider

    def select(self, required: set[str], preferred: str | None = None) -> ProviderSelection:
        candidates: list[ProviderSelection] = []
        for provider in self._providers.values():
            matched = len(required & set(provider.capabilities))
            coverage = matched / max(1, len(required))
            bonus = 0.1 if provider.name == preferred else 0.0
            reasons = (f'covers {matched}/{len(required)} required capabilities',)
            candidates.append(ProviderSelection(provider, min(1.0, coverage + bonus), reasons))
        if not candidates:
            raise LookupError('No model providers are registered')
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[0]

    def all(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))
