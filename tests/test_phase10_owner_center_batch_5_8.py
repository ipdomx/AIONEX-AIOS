from aios.mission_control.approval_center import ApprovalRequest, ApprovalState, OwnerApprovalCenter
from aios.mission_control.owner_alerts import AlertSeverity, AlertStatus, OwnerAlert, OwnerAlertService
from aios.mission_control.owner_reports import OwnerReportService
from aios.mission_control.project_controls import (
    OwnerProjectControlService,
    ProjectControl,
    ProjectControlState,
)


def test_owner_alert_lifecycle_and_scope() -> None:
    service = OwnerAlertService()
    service.publish(
        OwnerAlert(
            alert_id="a-1",
            owner_id="owner-1",
            source="runtime",
            title="Worker unavailable",
            message="worker-7 stopped responding",
            severity=AlertSeverity.CRITICAL,
        )
    )

    assert service.list_for_owner("owner-1")[0].status is AlertStatus.OPEN
    service.acknowledge("a-1", "owner-1")
    assert service.list_for_owner("owner-1")[0].status is AlertStatus.ACKNOWLEDGED
    service.resolve("a-1", "owner-1")
    assert service.list_for_owner("owner-1")[0].status is AlertStatus.RESOLVED


def test_owner_approval_center_prevents_double_decision() -> None:
    center = OwnerApprovalCenter()
    center.submit(
        ApprovalRequest(
            approval_id="approval-1",
            owner_id="owner-1",
            action="enable-provider",
            requested_by="manager-1",
            reason="project requirement",
        )
    )

    approved = center.approve("approval-1", "owner-1", "approved")
    assert approved.state is ApprovalState.APPROVED

    try:
        center.reject("approval-1", "owner-1")
    except RuntimeError:
        pass
    else:
        raise AssertionError("a decided request must not be decided again")


def test_project_controls_enforce_owner_scope_and_budget() -> None:
    service = OwnerProjectControlService()
    service.register(ProjectControl(project_id="project-1", owner_id="owner-1"))

    service.set_budget_limit("project-1", "owner-1", 500.0)
    service.set_service_enabled("project-1", "owner-1", "github", True)
    control = service.set_state("project-1", "owner-1", ProjectControlState.PAUSED)

    assert control.budget_limit == 500.0
    assert control.service_flags["github"] is True
    assert control.state is ProjectControlState.PAUSED


def test_owner_reports_are_isolated() -> None:
    service = OwnerReportService()
    report = service.generate(
        report_id="report-1",
        owner_id="owner-1",
        title="Daily owner brief",
        summary="All critical systems are healthy.",
        metrics={"active_projects": 4, "open_incidents": 0},
        sections={"approvals": ["No pending approvals"]},
    )

    assert service.get("report-1", "owner-1") is report
    assert service.list_for_owner("owner-1") == [report]
