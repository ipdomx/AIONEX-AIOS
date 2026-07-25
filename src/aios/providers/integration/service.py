from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..platform import MultiModelPlatform
from ..routing import AIRoutingLayer
from .firewall import PromptContextFirewall
from .journal import AIInteractionJournal
from .models import AIWorkItem, AIWorkResult


class AIProviderIntegration:
    """Connects provider routing to AIOS memory, audit and notification boundaries."""

    def __init__(
        self,
        platform: MultiModelPlatform,
        routing: AIRoutingLayer,
        journal_path: str | Path,
        *,
        knowledge: Any | None = None,
        notifier: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.platform = platform
        self.routing = routing
        self.knowledge = knowledge
        self.notifier = notifier
        self.firewall = PromptContextFirewall()
        self.journal = AIInteractionJournal(journal_path)

    async def execute(self, item: AIWorkItem) -> AIWorkResult:
        request, findings = self.firewall.sanitize(item.request)
        started = datetime.now(timezone.utc).isoformat()
        routed = await self.routing.execute(
            request,
            item.policy,
            project=item.project,
            budget_scope=item.budget_scope,
            priority=item.priority,
        )
        chosen = routed.selected
        result = AIWorkResult(
            task_id=item.task_id,
            provider=chosen.provider,
            model=chosen.model,
            text=chosen.text,
            confidence=chosen.confidence,
            strategy=routed.strategy,
            candidates=len(routed.candidates),
            cost=sum((candidate.response.cost if candidate.response else 0.0) for candidate in routed.candidates),
            latency_ms=sum((candidate.response.latency_ms if candidate.response else 0.0) for candidate in routed.candidates),
            metadata={"firewall_findings": findings, **item.metadata},
        )
        event = {
            "event": "ai-work-completed",
            "task_id": item.task_id,
            "project": item.project,
            "actor": item.actor,
            "provider": result.provider,
            "model": result.model,
            "strategy": result.strategy,
            "candidates": result.candidates,
            "cost": result.cost,
            "latency_ms": result.latency_ms,
            "confidence": result.confidence,
            "started_at": started,
            "completed_at": result.completed_at,
            "firewall_findings": list(findings),
        }
        self.journal.append(event)
        self._record_knowledge(item, result)
        if self.notifier is not None:
            self.notifier(event)
        return result

    def health(self) -> dict[str, Any]:
        return {
            "providers": len(self.platform.registry.all()),
            "journal_valid": self.journal.verify(),
            "routing_requests": self.routing.metrics.daily_report()["requests"],
        }

    def _record_knowledge(self, item: AIWorkItem, result: AIWorkResult) -> None:
        if self.knowledge is None or item.project is None:
            return
        record = getattr(self.knowledge, "record_outcome", None)
        if callable(record):
            try:
                from ...knowledge_learning.models import Outcome
                record(
                    "ai-provider-route",
                    {"project": item.project, "task_id": item.task_id, "provider": result.provider},
                    Outcome.SUCCESS,
                    (f"provider:{result.provider}", f"model:{result.model}"),
                    confidence=result.confidence,
                )
            except (ImportError, TypeError, ValueError):
                return
