from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from statistics import mean
from typing import Iterable


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    RATIO = "ratio"
    DURATION = "duration"


@dataclass(frozen=True)
class MetricRecord:
    name: str
    value: float
    metric_type: MetricType = MetricType.GAUGE
    organization_id: str | None = None
    project_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    labels: dict[str, str] = field(default_factory=dict)


class EnterpriseAnalytics:
    def __init__(self) -> None:
        self._records: list[MetricRecord] = []

    def record(self, record: MetricRecord) -> None:
        if not record.name.strip():
            raise ValueError("metric name is required")
        self._records.append(record)

    def query(
        self,
        name: str | None = None,
        organization_id: str | None = None,
        project_id: str | None = None,
    ) -> list[MetricRecord]:
        records: Iterable[MetricRecord] = self._records
        if name is not None:
            records = (record for record in records if record.name == name)
        if organization_id is not None:
            records = (record for record in records if record.organization_id == organization_id)
        if project_id is not None:
            records = (record for record in records if record.project_id == project_id)
        return list(records)

    def aggregate(self, name: str, operation: str = "mean") -> float:
        values = [record.value for record in self.query(name=name)]
        if not values:
            raise LookupError(f"no metric records found for {name}")
        operations = {
            "mean": lambda: mean(values),
            "sum": lambda: sum(values),
            "min": lambda: min(values),
            "max": lambda: max(values),
            "count": lambda: float(len(values)),
        }
        try:
            return float(operations[operation]())
        except KeyError as exc:
            raise ValueError(f"unsupported aggregate operation: {operation}") from exc

    def snapshot(self) -> dict[str, float]:
        names = sorted({record.name for record in self._records})
        return {name: self.aggregate(name) for name in names}
