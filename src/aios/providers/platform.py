from __future__ import annotations

import asyncio

from .adapters.catalog import default_providers
from .base import Transport
from .budget import CostGovernor
from .metrics import ProviderMetrics
from .models import ModelRequest, ModelResponse
from .policy import ProviderPolicy
from .registry import ProviderRegistry
from .router import ModelRouter


class MultiModelPlatform:
    def __init__(self, transports: dict[str, Transport] | None = None) -> None:
        self.registry = ProviderRegistry()
        for provider in default_providers(transports):
            self.registry.register(provider)
        self.policy = ProviderPolicy()
        self.costs = CostGovernor()
        self.metrics = ProviderMetrics()
        self.router = ModelRouter(self.registry, self.policy, self.costs)

    async def health_check(self) -> dict[str, str]:
        states = await asyncio.gather(*(provider.health_check() for provider in self.registry.all()))
        return {provider.name: state.value for provider, state in zip(self.registry.all(), states)}

    async def generate(self, request: ModelRequest, *, project: str | None = None,
                       budget_scope: str = "global") -> ModelResponse:
        decision = self.router.select(request, project=project, budget_scope=budget_scope)
        provider = self.registry.get(decision.provider)
        try:
            response = await provider.generate(request, decision.model)
        except Exception:
            self.metrics.record(provider.name, success=False)
            raise
        self.metrics.record(provider.name, success=True, latency_ms=response.latency_ms, cost=response.cost)
        self.costs.record(budget_scope, response.cost)
        return response

    async def compare(self, request: ModelRequest, *, count: int = 3, project: str | None = None,
                      budget_scope: str = "global") -> tuple[ModelResponse, ...]:
        routes = self.router.rank(request, project=project, budget_scope=budget_scope)[:max(1, count)]
        calls = [self.registry.get(route.provider).generate(request, route.model) for route in routes]
        raw = await asyncio.gather(*calls, return_exceptions=True)
        responses: list[ModelResponse] = []
        for route, item in zip(routes, raw):
            if isinstance(item, Exception):
                self.metrics.record(route.provider, success=False)
                continue
            self.metrics.record(route.provider, success=True, latency_ms=item.latency_ms, cost=item.cost)
            self.costs.record(budget_scope, item.cost)
            responses.append(item)
        return tuple(responses)
