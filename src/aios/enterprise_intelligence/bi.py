from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .analytics import EnterpriseAnalytics


class InsightSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Insight:
    title: str
    description: str
    severity: InsightSeverity
    metric_name: str
    metric_value: float
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BusinessIntelligenceEngine:
    def __init__(self, analytics: EnterpriseAnalytics) -> None:
        self.analytics = analytics

    def analyze_thresholds(self, thresholds: dict[str, tuple[float, float]]) -> list[Insight]:
        insights: list[Insight] = []
        snapshot = self.analytics.snapshot()
        for metric_name, value in snapshot.items():
            warning, critical = thresholds.get(metric_name, (float("inf"), float("inf")))
            if value >= critical:
                severity = InsightSeverity.CRITICAL
            elif value >= warning:
                severity = InsightSeverity.WARNING
            else:
                continue
            insights.append(
                Insight(
                    title=f"{metric_name} threshold exceeded",
                    description=f"Observed value {value:.2f}",
                    severity=severity,
                    metric_name=metric_name,
                    metric_value=value,
                )
            )
        return insights

    def summarize(self) -> dict[str, object]:
        snapshot = self.analytics.snapshot()
        return {
            "metrics": snapshot,
            "metric_count": len(snapshot),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
