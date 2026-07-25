from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .analytics import EnterpriseAnalytics
from .bi import BusinessIntelligenceEngine, Insight
from .kpi import KPI, KPIEngine


@dataclass(frozen=True)
class DashboardSnapshot:
    metrics: dict[str, float]
    kpis: dict[str, str]
    insights: list[Insight]
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ExecutiveDashboard:
    def __init__(
        self,
        analytics: EnterpriseAnalytics,
        bi_engine: BusinessIntelligenceEngine,
        kpi_engine: KPIEngine,
    ) -> None:
        self.analytics = analytics
        self.bi_engine = bi_engine
        self.kpi_engine = kpi_engine

    def snapshot(
        self,
        kpis: list[KPI] | None = None,
        thresholds: dict[str, tuple[float, float]] | None = None,
    ) -> DashboardSnapshot:
        return DashboardSnapshot(
            metrics=self.analytics.snapshot(),
            kpis=self.kpi_engine.scorecard(kpis or []),
            insights=self.bi_engine.analyze_thresholds(thresholds or {}),
        )
