from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date


@dataclass(slots=True)
class RoutingMetric:
    requests: int = 0
    successes: int = 0
    errors: int = 0
    tokens: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0


class RoutingMetrics:
    def __init__(self) -> None:
        self._providers: dict[str, RoutingMetric] = defaultdict(RoutingMetric)
        self._daily: dict[str, RoutingMetric] = defaultdict(RoutingMetric)

    def record(self, provider: str, *, success: bool, tokens: int = 0,
               cost: float = 0.0, latency_ms: float = 0.0) -> None:
        for metric in (self._providers[provider], self._daily[date.today().isoformat()]):
            metric.requests += 1
            metric.successes += int(success)
            metric.errors += int(not success)
            metric.tokens += max(0, tokens)
            metric.cost += max(0.0, cost)
            metric.latency_ms += max(0.0, latency_ms)

    def provider_report(self, provider: str) -> dict[str, float | int]:
        item = self._providers[provider]
        return self._serialize(item)

    def daily_report(self, day: str | None = None) -> dict[str, float | int]:
        return self._serialize(self._daily[day or date.today().isoformat()])

    def monthly_report(self, month: str) -> dict[str, float | int]:
        aggregate = RoutingMetric()
        for day, item in self._daily.items():
            if day.startswith(month):
                aggregate.requests += item.requests
                aggregate.successes += item.successes
                aggregate.errors += item.errors
                aggregate.tokens += item.tokens
                aggregate.cost += item.cost
                aggregate.latency_ms += item.latency_ms
        return self._serialize(aggregate)

    @staticmethod
    def _serialize(item: RoutingMetric) -> dict[str, float | int]:
        return {"requests": item.requests, "successes": item.successes, "errors": item.errors,
                "success_rate": item.successes / item.requests if item.requests else 0.0,
                "error_rate": item.errors / item.requests if item.requests else 0.0,
                "tokens": item.tokens, "cost": item.cost,
                "average_latency_ms": item.latency_ms / item.requests if item.requests else 0.0}
