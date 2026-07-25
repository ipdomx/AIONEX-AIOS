from __future__ import annotations

from .budget import CostGovernor
from .errors import NoEligibleProvider
from .models import ModelRequest, RouteDecision
from .policy import ProviderPolicy
from .registry import ProviderRegistry


class ModelRouter:
    def __init__(self, registry: ProviderRegistry, policy: ProviderPolicy, costs: CostGovernor):
        self.registry = registry
        self.policy = policy
        self.costs = costs

    @staticmethod
    def estimate_cost(capability, request: ModelRequest) -> float:
        output = max(1, request.max_tokens)
        input_tokens = max(1, len(request.prompt) // 4 + len(request.system_prompt) // 4)
        return (input_tokens * capability.input_cost_per_million + output * capability.output_cost_per_million) / 1_000_000

    def rank(self, request: ModelRequest, *, project: str | None = None, budget_scope: str = "global") -> tuple[RouteDecision, ...]:
        decisions: list[RouteDecision] = []
        for provider in self.registry.all():
            if not provider.enabled:
                continue
            for cap in provider.capabilities():
                if request.task not in cap.tasks and "general" not in cap.tasks:
                    continue
                allowed, reason = self.policy.allows(cap, request, project)
                if not allowed:
                    continue
                cost = self.estimate_cost(cap, request)
                if request.max_cost is not None and cost > request.max_cost:
                    continue
                if not self.costs.authorize(budget_scope, cost):
                    continue
                quality = cap.quality_score * .45
                latency = cap.latency_score * .15
                privacy = cap.privacy_score * .25
                economy = max(0.0, 1.0 - min(cost * 1000, 1.0)) * .15
                score = round(quality + latency + privacy + economy, 6)
                reasons = ("task-compatible", reason, "budget-compatible", "policy-compatible")
                decisions.append(RouteDecision(provider.name, cap.model, score, cost, reasons))
        decisions.sort(key=lambda item: (-item.score, item.estimated_cost, item.provider, item.model))
        return tuple(decisions)

    def select(self, request: ModelRequest, *, project: str | None = None, budget_scope: str = "global") -> RouteDecision:
        ranked = self.rank(request, project=project, budget_scope=budget_scope)
        if not ranked:
            raise NoEligibleProvider("no provider satisfies task, privacy, policy, and budget constraints")
        return ranked[0]
