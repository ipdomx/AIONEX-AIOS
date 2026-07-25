from __future__ import annotations

import asyncio

from .analytics import RoutingMetrics
from .consensus import BestResultSelector, ConsensusEngine, VotingEngine
from .health import ProviderHealthSystem
from .models import CandidateResult, ExecutionMode, OptimizationMode, RoutedResult, RoutingPolicy
from .queueing import QueueManager, RequestScheduler
from ..models import ModelRequest, ModelResponse, RouteDecision


class AIRoutingLayer:
    def __init__(self, platform, *, max_concurrency: int = 8, queue_workers: int = 2) -> None:
        self.platform = platform
        self.health = ProviderHealthSystem()
        self.metrics = RoutingMetrics()
        self.scheduler = RequestScheduler(max_concurrency)
        self.queue = QueueManager(queue_workers)

    def rank(self, request: ModelRequest, policy: RoutingPolicy | None = None,
             *, project: str | None = None, budget_scope: str = "global") -> tuple[RouteDecision, ...]:
        policy = policy or RoutingPolicy()
        decisions = list(self.platform.router.rank(request, project=project, budget_scope=budget_scope))
        decisions = [item for item in decisions if item.provider not in policy.excluded_providers]
        if policy.offline_only or policy.privacy_mode:
            decisions = [item for item in decisions if self.platform.registry.get(item.provider).capability(item.model).local]
        decisions = [item for item in decisions if self.health.available(item.provider)]
        priority = {name: index for index, name in enumerate(policy.provider_priority)}

        def key(item: RouteDecision):
            cap = self.platform.registry.get(item.provider).capability(item.model)
            preferred = priority.get(item.provider, len(priority))
            if policy.optimization == OptimizationMode.COST:
                value = (item.estimated_cost, -item.score)
            elif policy.optimization == OptimizationMode.SPEED:
                value = (-cap.latency_score, -item.score)
            elif policy.optimization == OptimizationMode.QUALITY:
                value = (-cap.quality_score, item.estimated_cost)
            elif policy.optimization == OptimizationMode.PRIVACY:
                value = (-cap.privacy_score, not cap.local, item.estimated_cost)
            else:
                value = (-item.score, item.estimated_cost)
            return (preferred, *value, item.provider, item.model)

        return tuple(sorted(decisions, key=key))

    async def execute(self, request: ModelRequest, policy: RoutingPolicy | None = None,
                      *, project: str | None = None, budget_scope: str = "global",
                      priority: int = 100) -> RoutedResult:
        policy = policy or RoutingPolicy()
        ranked = self.rank(request, policy, project=project, budget_scope=budget_scope)
        if not ranked:
            raise RuntimeError("no eligible route")
        count = max(1, policy.max_models if policy.execution != ExecutionMode.SINGLE else 1)
        selected_routes = ranked[:count]

        async def operation() -> RoutedResult:
            candidates = await asyncio.gather(*(self._call(item, request, policy.timeout_seconds)
                                                for item in selected_routes))
            results = tuple(candidates)
            successful = tuple(item for item in results if item.successful)
            if not successful and policy.allow_failover:
                for decision in ranked[count:]:
                    result = await self._call(decision, request, policy.timeout_seconds)
                    results += (result,)
                    if result.successful:
                        successful += (result,)
                        break
            if not successful:
                raise RuntimeError("all routed model calls failed")
            if policy.execution == ExecutionMode.VOTE:
                chosen = VotingEngine.select(successful)
                strategy = "vote"
            elif policy.execution == ExecutionMode.CONSENSUS:
                chosen = ConsensusEngine.synthesize(successful)
                strategy = "consensus"
            else:
                chosen = BestResultSelector.select(successful)
                strategy = "best-result" if len(successful) > 1 else "single"
            return RoutedResult(chosen, results, strategy,
                                {"ranked_routes": len(ranked), "executed_routes": len(results)})

        return await self.queue.submit(operation, priority=priority)

    async def _call(self, decision: RouteDecision, request: ModelRequest, timeout: float) -> CandidateResult:
        provider = self.platform.registry.get(decision.provider)
        try:
            response: ModelResponse = await self.scheduler.run(
                lambda: provider.generate(request, decision.model), timeout)
            self.health.record_success(decision.provider, response.latency_ms)
            self.metrics.record(decision.provider, success=True,
                                tokens=response.input_tokens + response.output_tokens,
                                cost=response.cost, latency_ms=response.latency_ms)
            return CandidateResult(decision, response)
        except Exception as exc:
            self.health.record_failure(decision.provider, exc)
            self.metrics.record(decision.provider, success=False)
            return CandidateResult(decision, None, str(exc))
