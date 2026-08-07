"""Phase 29J final provider/model contract.

This module is intentionally truthful: providers without a configured transport or
credential reference remain unavailable and are never reported as active.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SUPPORTED_PROVIDERS = (
    "openai", "anthropic", "gemini", "openrouter", "ollama",
    "mistral", "cohere", "xai", "deepseek", "groq", "together",
    "fireworks", "huggingface", "azure_openai", "aws_bedrock",
)

SUPPORTED_CAPABILITIES = frozenset({
    "text", "reasoning", "coding", "tools", "streaming", "structured_output",
    "embeddings", "vision", "image", "audio", "video", "3d", "files",
})


class ActivationState(str, Enum):
    ACTIVE = "active"
    UNCONFIGURED = "unconfigured"
    DISABLED = "disabled"
    REMOVED = "removed"


@dataclass(slots=True)
class ProviderContract:
    provider_id: str
    credential_ref: str | None = None
    endpoint: str | None = None
    enabled: bool = False
    local: bool = False
    capabilities: frozenset[str] = field(default_factory=frozenset)
    models: tuple[str, ...] = ()
    max_requests_per_minute: int = 60
    daily_budget: float | None = None
    allow_fallback: bool = False
    safety_required: bool = True
    removed: bool = False

    @property
    def state(self) -> ActivationState:
        if self.removed:
            return ActivationState.REMOVED
        if not self.enabled:
            return ActivationState.DISABLED if (self.credential_ref or self.local) else ActivationState.UNCONFIGURED
        if self.local or self.credential_ref:
            return ActivationState.ACTIVE
        return ActivationState.UNCONFIGURED


class FinalProviderRegistry:
    def __init__(self) -> None:
        self.providers: dict[str, ProviderContract] = {}

    def register(self, contract: ProviderContract) -> ProviderContract:
        if contract.provider_id not in SUPPORTED_PROVIDERS:
            raise ValueError("provider is not in the supported Phase 29J contract")
        unsupported = set(contract.capabilities) - set(SUPPORTED_CAPABILITIES)
        if unsupported:
            raise ValueError(f"unsupported provider capabilities: {sorted(unsupported)}")
        self.providers[contract.provider_id] = contract
        return contract

    def inventory(self) -> tuple[dict[str, Any], ...]:
        rows = []
        for provider_id in SUPPORTED_PROVIDERS:
            item = self.providers.get(provider_id) or ProviderContract(provider_id)
            rows.append({
                "provider": provider_id,
                "state": item.state.value,
                "configured": bool(item.credential_ref or item.local),
                "enabled": item.enabled,
                "local": item.local,
                "models": list(item.models),
                "capabilities": sorted(item.capabilities),
                "budget": item.daily_budget,
                "rate_limit": item.max_requests_per_minute,
                "fallback": item.allow_fallback,
                "safety_required": item.safety_required,
            })
        return tuple(rows)

    def activate(self, provider_id: str) -> ProviderContract:
        item = self.providers[provider_id]
        if not (item.local or item.credential_ref):
            raise RuntimeError("provider credentials or local runtime are not configured")
        item.enabled = True
        return item

    def disable(self, provider_id: str) -> ProviderContract:
        item = self.providers[provider_id]; item.enabled = False; return item

    def remove(self, provider_id: str) -> ProviderContract:
        item = self.providers.get(provider_id) or ProviderContract(provider_id)
        item.enabled = False; item.removed = True; self.providers[provider_id] = item; return item

    def discover_models(self, provider_id: str) -> tuple[str, ...]:
        item = self.providers[provider_id]
        if item.state is not ActivationState.ACTIVE:
            return ()
        return item.models

    def select(self, *, capability: str, preferred: tuple[str, ...] = (), allow_fallback: bool = False) -> ProviderContract:
        if capability not in SUPPORTED_CAPABILITIES:
            raise ValueError("unknown capability")
        ordered = list(preferred) + [p for p in SUPPORTED_PROVIDERS if p not in preferred]
        eligible = [self.providers[p] for p in ordered if p in self.providers and self.providers[p].state is ActivationState.ACTIVE and capability in self.providers[p].capabilities]
        if not eligible:
            raise RuntimeError("no active provider supports the requested capability")
        if preferred and eligible[0].provider_id not in preferred and not allow_fallback:
            raise RuntimeError("preferred provider unavailable and fallback is disabled")
        return eligible[0]
