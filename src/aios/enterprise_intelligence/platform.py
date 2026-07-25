from __future__ import annotations

from dataclasses import dataclass

from .analytics import EnterpriseAnalytics
from .bi import BusinessIntelligenceEngine
from .dashboard import ExecutiveDashboard
from .kpi import KPIEngine
from .reports import EnterpriseReportBuilder
from .strategy import StrategicPlanningEngine


@dataclass
class EnterpriseIntelligencePlatform:
    analytics: EnterpriseAnalytics
    bi: BusinessIntelligenceEngine
    kpis: KPIEngine
    reports: EnterpriseReportBuilder
    strategy: StrategicPlanningEngine
    dashboard: ExecutiveDashboard

    @classmethod
    def build_default(cls) -> "EnterpriseIntelligencePlatform":
        analytics = EnterpriseAnalytics()
        bi = BusinessIntelligenceEngine(analytics)
        kpis = KPIEngine()
        reports = EnterpriseReportBuilder()
        strategy = StrategicPlanningEngine()
        dashboard = ExecutiveDashboard(analytics, bi, kpis)
        return cls(
            analytics=analytics,
            bi=bi,
            kpis=kpis,
            reports=reports,
            strategy=strategy,
            dashboard=dashboard,
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "analytics": self.analytics is not None,
            "business_intelligence": self.bi is not None,
            "kpi_engine": self.kpis is not None,
            "reports": self.reports is not None,
            "strategic_planning": self.strategy is not None,
            "executive_dashboard": self.dashboard is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
