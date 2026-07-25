from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(slots=True)
class ProviderMetric:
    calls: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0.0
    total_cost: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.calls if self.calls else 0.0


class ProviderMetrics:
    def __init__(self) -> None:
        self._data: dict[str, ProviderMetric] = defaultdict(ProviderMetric)

    def record(self, provider: str, *, success: bool, latency_ms: float = 0.0, cost: float = 0.0) -> None:
        item = self._data[provider]
        item.calls += 1
        item.successes += int(success)
        item.failures += int(not success)
        item.total_latency_ms += max(0.0, latency_ms)
        item.total_cost += max(0.0, cost)

    def get(self, provider: str) -> ProviderMetric:
        return self._data[provider]
