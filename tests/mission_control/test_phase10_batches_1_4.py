from datetime import datetime, timezone

import pytest

from aios.mission_control.audit import OwnerAuditLog
from aios.mission_control.domain import (
    ApprovalRequest,
    CommandPriority,
    CommandStatus,
    IncidentSnapshot,
    OwnerCommand,
    OwnerScope,
    ProjectSnapshot,
)
from aios.mission_control.overview import build_owner_overview
from aios.mission_control.service import AuthorizationError, MissionControlService


def scope() -> OwnerScope:
    return OwnerScope(
        owner_id="owner-1",
        organization_ids=frozenset({"org-1"}),
        project_ids=frozenset({"project-1"}),
    )


def test_owner_command_lifecycle() -> None:
    service = MissionControlService()
    command = OwnerCommand(
        command_id="cmd-1",
        owner_id="owner-1",
        action="pause",
        target_type="project",
        target_id="project-1",
        priority=CommandPriority.CRITICAL,
    )
    submitted = service.submit_command(scope(), command)
    assert submitted.status is CommandStatus.PENDING
    approved = service.approve_command(scope(), "cmd-1", "owner-1")
    assert approved.status is CommandStatus.APPROVED
    assert service.start_command("cmd-1").status is CommandStatus.EXECUTING
    completed = service.complete_command("cmd-1", {"paused": True})
    assert completed.status is CommandStatus.COMPLETED


def test_owner_scope_blocks_foreign_project() -> None:
    service = MissionControlService()
    with pytest.raises(AuthorizationError):
        service.submit_command(
            scope(),
            OwnerCommand(
                command_id="cmd-2",
                owner_id="owner-1",
                action="pause",
                target_type="project",
                target_id="project-2",
            ),
        )


def test_snapshot_and_owner_overview() -> None:
    now = datetime.now(timezone.utc)
    snapshot = MissionControlService.build_snapshot(
        scope(),
        projects=[
            ProjectSnapshot("project-1", "org-1", "running", 50.0, 3, 1, 0, 1200, "EUR", 0.4, now),
            ProjectSnapshot("project-2", "org-2", "running", 10.0, 1, 0, 0, 900, "EUR", 0.2, now),
        ],
        incidents=[
            IncidentSnapshot("inc-1", "critical", "open", "runtime", "failure", "project-1", now),
        ],
        approvals=[
            ApprovalRequest("app-1", "worker-1", "project", "project-1", "deploy", "owner approval", now),
        ],
        active_workers=4,
        unhealthy_workers=1,
        queued_tasks=7,
        running_tasks=3,
        completed_tasks_24h=20,
        failed_tasks_24h=2,
    )
    assert len(snapshot.projects) == 1
    overview = build_owner_overview(snapshot)
    assert overview["summary"]["projects"] == 1
    assert overview["summary"]["critical_incidents"] == 1
    assert overview["summary"]["total_cost_minor"] == 1200


def test_audit_log_chain_is_valid() -> None:
    audit = OwnerAuditLog()
    audit.append(
        event_id="event-1",
        actor_id="owner-1",
        action="approve",
        subject_type="command",
        subject_id="cmd-1",
    )
    audit.append(
        event_id="event-2",
        actor_id="owner-1",
        action="complete",
        subject_type="command",
        subject_id="cmd-1",
        payload={"ok": True},
    )
    assert audit.verify_chain()
    assert len(audit.list_events(subject_type="command", subject_id="cmd-1")) == 2
