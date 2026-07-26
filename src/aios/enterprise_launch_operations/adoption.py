from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class AdoptionMetric:
    name: str
    value: float
    organization_id: str | None = None
    user_segment: str | None = None
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)


class AdoptionTracker:
    def __init__(self) -> None:
        self._metrics: list[AdoptionMetric] = []

    def record(self, metric: AdoptionMetric) -> AdoptionMetric:
        if not metric.name.strip():
            raise ValueError("metric name is required")
        self._metrics.append(metric)
        return metric

    def list(self, name: str | None = None, organization_id: str | None = None) -> list[AdoptionMetric]:
        metrics = self._metrics
        if name is not None:
            metrics = [metric for metric in metrics if metric.name == name]
        if organization_id is not None:
            metrics = [metric for metric in metrics if metric.organization_id == organization_id]
        return list(metrics)

    def average(self, name: str) -> float:
        values = [metric.value for metric in self.list(name=name)]
        if not values:
            raise LookupError(f"adoption metric not found: {name}")
        return sum(values) / len(values)

    def snapshot(self) -> dict[str, float]:
        names = sorted({metric.name for metric in self._metrics})
        return {name: self.average(name) for name in names}
