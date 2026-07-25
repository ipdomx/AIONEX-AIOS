from aios.enterprise_intelligence import (
    EnterpriseAnalytics,
    EnterpriseIntelligencePlatform,
    KPI,
    KPIEngine,
    KPIStatus,
    MetricRecord,
    ReportSection,
    StrategicObjective,
)
from aios.enterprise_intelligence.strategy import ObjectiveStatus


def test_enterprise_analytics_and_dashboard() -> None:
    platform = EnterpriseIntelligencePlatform.build_default()
    platform.analytics.record(MetricRecord(name="incident_rate", value=4.0))
    platform.analytics.record(MetricRecord(name="incident_rate", value=8.0))

    snapshot = platform.dashboard.snapshot(
        kpis=[KPI(name="availability", current=99.95, target=99.9)],
        thresholds={"incident_rate": (5.0, 7.0)},
    )

    assert snapshot.metrics["incident_rate"] == 6.0
    assert snapshot.kpis["availability"] == KPIStatus.ON_TRACK.value
    assert len(snapshot.insights) == 1


def test_strategic_plan_and_report() -> None:
    platform = EnterpriseIntelligencePlatform.build_default()
    objective = StrategicObjective(
        objective_id="obj-1",
        title="Improve reliability",
        status=ObjectiveStatus.COMPLETED,
    )
    plan = platform.strategy.create_plan("plan-1", "Enterprise Reliability", [objective])
    report = platform.reports.build(
        "Executive Report",
        [ReportSection(title="Strategy", data={"progress": platform.strategy.progress(plan)})],
    )

    assert platform.strategy.progress(plan) == 1.0
    assert report.sections[0].data["progress"] == 1.0
    assert platform.validate()["ready"] is True
