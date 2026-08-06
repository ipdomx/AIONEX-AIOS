"""Durable provider-neutral work management for Phase 29F."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AuditEvent,
    Project,
    ProjectEvent,
    ProjectMembership,
    Report,
    Task,
    TaskComment,
    User,
    Workflow,
    WorkflowRun,
    WorkforceMember,
    uuid_str,
)

PROJECT_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "start": (frozenset({"planning", "approved", "paused"}), "active"),
    "resume": (frozenset({"paused"}), "active"),
    "pause": (frozenset({"planning", "active", "in_progress", "review"}), "paused"),
    "request_review": (frozenset({"active", "in_progress", "paused"}), "review"),
    "approve": (frozenset({"review"}), "approved"),
    "reject": (frozenset({"review"}), "rework"),
    "rework": (frozenset({"review", "approved", "rework"}), "active"),
    "complete": (frozenset({"approved", "active", "review"}), "completed"),
    "cancel": (frozenset({"planning", "active", "paused", "review", "rework"}), "cancelled"),
    "archive": (frozenset({"completed", "cancelled"}), "archived"),
    "restore": (frozenset({"archived"}), "completed"),
}
TASK_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "start": (frozenset({"todo", "rework", "paused"}), "in_progress"),
    "pause": (frozenset({"in_progress"}), "paused"),
    "resume": (frozenset({"paused"}), "in_progress"),
    "request_review": (frozenset({"in_progress", "paused"}), "review"),
    "approve": (frozenset({"review"}), "done"),
    "rework": (frozenset({"review", "done"}), "rework"),
    "complete": (frozenset({"in_progress", "review"}), "done"),
    "cancel": (frozenset({"todo", "in_progress", "paused", "review", "rework"}), "cancelled"),
    "reopen": (frozenset({"done", "cancelled"}), "todo"),
}


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def checksum(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def project_event_snapshot(item: ProjectEvent) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "actor_id": item.actor_id,
        "event_type": item.event_type,
        "from_status": item.from_status,
        "to_status": item.to_status,
        "summary": item.summary,
        "details": item.details,
        "created_at": iso(item.created_at),
    }


def membership_snapshot(item: ProjectMembership) -> dict[str, Any]:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "user_id": item.user_id,
        "workforce_member_id": item.workforce_member_id,
        "member_key": item.member_key,
        "member_type": item.member_type,
        "role": item.role,
        "allocation_percent": item.allocation_percent,
        "status": item.status,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def comment_snapshot(item: TaskComment) -> dict[str, Any]:
    return {
        "id": item.id,
        "task_id": item.task_id,
        "author_id": item.author_id,
        "workforce_member_id": item.workforce_member_id,
        "visibility": item.visibility,
        "body": item.body,
        "attachments": item.attachments,
        "created_at": iso(item.created_at),
    }


def workflow_run_snapshot(item: WorkflowRun) -> dict[str, Any]:
    return {
        "id": item.id,
        "workflow_id": item.workflow_id,
        "project_id": item.project_id,
        "requested_by_id": item.requested_by_id,
        "status": item.status,
        "current_step": item.current_step,
        "attempt_count": item.attempt_count,
        "input": item.input,
        "output": item.output,
        "evidence": item.evidence,
        "error_code": item.error_code,
        "error_message": item.error_message,
        "started_at": iso(item.started_at),
        "completed_at": iso(item.completed_at),
        "cancelled_at": iso(item.cancelled_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def report_snapshot(item: Report) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "workspace_id": item.workspace_id,
        "project_id": item.project_id,
        "generated_by_id": item.generated_by_id,
        "name": item.name,
        "type": item.type,
        "status": item.status,
        "summary": item.summary,
        "metrics": item.metrics,
        "format": item.format,
        "checksum": item.checksum,
        "size_bytes": item.size_bytes,
        "version": item.version,
        "archived_at": iso(item.archived_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


async def record_project_event(
    session: AsyncSession,
    project: Project,
    *,
    actor_id: str | None,
    event_type: str,
    from_status: str | None = None,
    to_status: str | None = None,
    summary: str | None = None,
    details: dict[str, Any] | None = None,
) -> ProjectEvent:
    event = ProjectEvent(
        id=uuid_str(),
        organization_id=project.organization_id,
        project_id=project.id,
        actor_id=actor_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        summary=(summary or "").strip() or None,
        details=details or {},
        created_at=now(),
    )
    session.add(event)
    return event


async def ensure_project_owner_membership(
    session: AsyncSession, project: Project
) -> ProjectMembership:
    member_key = f"user:{project.owner_id}"
    item = await session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.member_key == member_key,
        )
    )
    if item is None:
        item = ProjectMembership(
            id=uuid_str(),
            organization_id=project.organization_id,
            project_id=project.id,
            user_id=project.owner_id,
            member_key=member_key,
            member_type="human",
            role="owner",
            allocation_percent=100,
            status="active",
        )
        session.add(item)
        await record_project_event(
            session,
            project,
            actor_id=project.owner_id,
            event_type="project.member.added",
            summary="Project owner registered as a durable member.",
            details={"member_key": member_key, "role": "owner"},
        )
    return item


async def add_project_member(
    session: AsyncSession,
    actor: UserRecord,
    project: Project,
    *,
    user_id: str | None,
    workforce_member_id: str | None,
    role: str,
    allocation_percent: int,
) -> ProjectMembership:
    if bool(user_id) == bool(workforce_member_id):
        raise ValueError("Select exactly one human user or workforce member")
    member_type = "human" if user_id else "digital"
    if user_id:
        user = await session.scalar(
            select(User).where(
                User.id == user_id,
                User.organization_id == project.organization_id,
                User.deleted_at.is_(None),
            )
        )
        if user is None:
            raise LookupError("Project member user not found")
        key = f"user:{user.id}"
    else:
        worker = await session.scalar(
            select(WorkforceMember).where(
                WorkforceMember.id == workforce_member_id,
                WorkforceMember.organization_id == project.organization_id,
                WorkforceMember.status.notin_({"retired", "deleted"}),
            )
        )
        if worker is None:
            raise LookupError("Project workforce member not found")
        key = f"worker:{worker.id}"
    item = await session.scalar(
        select(ProjectMembership)
        .where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.member_key == key,
        )
        .with_for_update()
    )
    if item is None:
        item = ProjectMembership(
            id=uuid_str(),
            organization_id=project.organization_id,
            project_id=project.id,
            user_id=user_id,
            workforce_member_id=workforce_member_id,
            member_key=key,
            member_type=member_type,
        )
        session.add(item)
    item.role = role.strip().lower() or "contributor"
    item.allocation_percent = max(1, min(100, allocation_percent))
    item.status = "active"
    await record_project_event(
        session,
        project,
        actor_id=actor.id,
        event_type="project.member.added",
        summary="Project membership added or restored.",
        details={"member_key": key, "role": item.role, "allocation_percent": item.allocation_percent},
    )
    session.add(
        AuditEvent(
            organization_id=project.organization_id,
            user_id=actor.id,
            action="project.member.updated",
            resource_type="project",
            resource_id=project.id,
            details={"member_key": key, "role": item.role},
        )
    )
    await session.flush()
    return item


async def transition_project(
    session: AsyncSession,
    actor: UserRecord,
    project: Project,
    *,
    action: str,
    reason: str = "",
) -> Project:
    normalized = action.strip().lower()
    transition = PROJECT_TRANSITIONS.get(normalized)
    if transition is None:
        raise ValueError("Unsupported project transition")
    allowed, target = transition
    if project.status not in allowed:
        raise ValueError(f"Project cannot {normalized} from status {project.status}")
    previous = project.status
    current = now()
    project.status = target
    project.version += 1
    if normalized == "request_review":
        project.review_status = "pending"
    elif normalized == "approve":
        project.review_status = "approved"
        project.approved_by_id = actor.id
        project.approved_at = current
    elif normalized in {"reject", "rework"}:
        project.review_status = "changes_requested"
        project.approved_by_id = None
        project.approved_at = None
    elif normalized == "complete":
        project.completed_at = current
        project.progress = 100
    elif normalized == "cancel":
        project.cancelled_at = current
    elif normalized == "archive":
        project.archived_at = current
    elif normalized == "restore":
        project.archived_at = None
    elif normalized in {"start", "resume"}:
        project.progress = max(project.progress, 1)
    await record_project_event(
        session,
        project,
        actor_id=actor.id,
        event_type=f"project.{normalized}",
        from_status=previous,
        to_status=target,
        summary=reason,
        details={"version": project.version, "review_status": project.review_status},
    )
    session.add(
        AuditEvent(
            organization_id=project.organization_id,
            user_id=actor.id,
            action=f"project.{normalized}",
            resource_type="project",
            resource_id=project.id,
            details={"from": previous, "to": target, "reason_present": bool(reason.strip())},
        )
    )
    return project


async def project_history(
    session: AsyncSession, project: Project, *, limit: int = 200
) -> list[ProjectEvent]:
    return list(
        (
            await session.scalars(
                select(ProjectEvent)
                .where(
                    ProjectEvent.organization_id == project.organization_id,
                    ProjectEvent.project_id == project.id,
                )
                .order_by(ProjectEvent.created_at.desc())
                .limit(limit)
            )
        ).all()
    )


async def transition_task(
    session: AsyncSession,
    actor: UserRecord,
    task: Task,
    *,
    action: str,
    reason: str = "",
) -> Task:
    normalized = action.strip().lower()
    transition = TASK_TRANSITIONS.get(normalized)
    if transition is None:
        raise ValueError("Unsupported task transition")
    allowed, target = transition
    if task.status not in allowed:
        raise ValueError(f"Task cannot {normalized} from status {task.status}")
    previous = task.status
    current = now()
    task.status = target
    task.version += 1
    if normalized == "request_review":
        task.review_status = "pending"
    elif normalized in {"approve", "complete"}:
        task.review_status = "approved"
        task.completed_at = current
    elif normalized == "rework":
        task.review_status = "changes_requested"
        task.rework_count += 1
        task.completed_at = None
    elif normalized == "cancel":
        task.cancelled_at = current
    elif normalized == "reopen":
        task.cancelled_at = None
        task.completed_at = None
        task.review_status = "not_requested"
    session.add(
        AuditEvent(
            organization_id=task.organization_id,
            user_id=actor.id,
            action=f"task.{normalized}",
            resource_type="task",
            resource_id=task.id,
            details={
                "from": previous,
                "to": target,
                "reason": reason.strip() or None,
                "version": task.version,
                "rework_count": task.rework_count,
            },
        )
    )
    if task.project_id:
        project = await session.get(Project, task.project_id)
        if project is not None:
            await record_project_event(
                session,
                project,
                actor_id=actor.id,
                event_type=f"task.{normalized}",
                summary=reason or task.title,
                details={"task_id": task.id, "from": previous, "to": target},
            )
    return task


async def add_task_comment(
    session: AsyncSession,
    actor: UserRecord,
    task: Task,
    *,
    body: str,
    visibility: str = "organization",
    attachments: Sequence[dict[str, Any]] = (),
) -> TaskComment:
    normalized = body.strip()
    if not normalized:
        raise ValueError("Task comment cannot be empty")
    item = TaskComment(
        id=uuid_str(),
        organization_id=task.organization_id,
        task_id=task.id,
        author_id=actor.id,
        visibility=visibility,
        body=normalized,
        attachments=list(attachments),
        created_at=now(),
    )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=task.organization_id,
            user_id=actor.id,
            action="task.comment.created",
            resource_type="task",
            resource_id=task.id,
            details={"comment_id": item.id, "visibility": visibility},
        )
    )
    return item


async def execute_workflow(
    session: AsyncSession,
    actor: UserRecord,
    workflow: Workflow,
    *,
    input_payload: dict[str, Any] | None = None,
) -> WorkflowRun:
    if workflow.status in {"deleted", "archived", "disabled"}:
        raise ValueError("Workflow is not executable")
    run = WorkflowRun(
        id=uuid_str(),
        organization_id=workflow.organization_id,
        workflow_id=workflow.id,
        project_id=workflow.project_id,
        requested_by_id=actor.id,
        status="running",
        current_step=0,
        attempt_count=1,
        input=input_payload or {},
        output={},
        evidence=[],
        started_at=now(),
    )
    session.add(run)
    await session.flush()
    output: dict[str, Any] = dict(run.input)
    evidence: list[dict[str, Any]] = []
    try:
        for index, raw_step in enumerate(workflow.steps or [], start=1):
            if not isinstance(raw_step, dict):
                raise ValueError(f"Workflow step {index} is invalid")
            step_type = str(raw_step.get("type") or "noop").strip().lower()
            run.current_step = index
            if step_type == "noop":
                evidence.append({"step": index, "type": step_type, "status": "completed"})
            elif step_type == "set":
                key = str(raw_step.get("key") or "").strip()
                if not key or len(key) > 160:
                    raise ValueError(f"Workflow step {index} has an invalid key")
                output[key] = raw_step.get("value")
                evidence.append({"step": index, "type": step_type, "key": key, "status": "completed"})
            elif step_type in {"evidence", "validation"}:
                label = str(
                    raw_step.get("label")
                    or raw_step.get("id")
                    or f"step-{index}"
                ).strip()[:200]
                evidence.append(
                    {
                        "step": index,
                        "type": step_type,
                        "label": label,
                        "status": "verified",
                    }
                )
            elif step_type == "task_status":
                task_id = str(raw_step.get("task_id") or "")
                target = str(raw_step.get("status") or "")
                task = await session.scalar(
                    select(Task).where(
                        Task.id == task_id,
                        Task.organization_id == workflow.organization_id,
                        Task.status != "deleted",
                    )
                )
                if task is None or target not in {"todo", "in_progress", "review", "done", "paused", "cancelled", "rework"}:
                    raise ValueError(f"Workflow step {index} task transition is invalid")
                previous = task.status
                task.status = target
                task.version += 1
                evidence.append({"step": index, "type": step_type, "task_id": task.id, "from": previous, "to": target})
            elif step_type == "project_status":
                project_id = str(raw_step.get("project_id") or workflow.project_id or "")
                target = str(raw_step.get("status") or "")
                project = await session.scalar(
                    select(Project).where(
                        Project.id == project_id,
                        Project.organization_id == workflow.organization_id,
                        Project.status != "deleted",
                    )
                )
                if project is None or target not in {"planning", "active", "paused", "review", "approved", "completed", "cancelled", "archived", "rework"}:
                    raise ValueError(f"Workflow step {index} project transition is invalid")
                previous = project.status
                project.status = target
                project.version += 1
                await record_project_event(
                    session,
                    project,
                    actor_id=actor.id,
                    event_type="workflow.project_status",
                    from_status=previous,
                    to_status=target,
                    details={"workflow_id": workflow.id, "run_id": run.id, "step": index},
                )
                evidence.append({"step": index, "type": step_type, "project_id": project.id, "from": previous, "to": target})
            else:
                raise ValueError(f"Workflow step {index} type is unsupported")
        run.status = "completed"
        run.output = output
        run.evidence = evidence
        run.completed_at = now()
        workflow.status = "active"
        workflow.run_count += 1
        workflow.last_run_at = run.completed_at
        workflow.version += 1
    except Exception as exc:
        run.status = "failed"
        run.output = output
        run.evidence = evidence
        run.error_code = type(exc).__name__
        run.error_message = str(exc)[:2000]
        run.completed_at = now()
    session.add(
        AuditEvent(
            organization_id=workflow.organization_id,
            user_id=actor.id,
            action="workflow.run" if run.status == "completed" else "workflow.run.failed",
            resource_type="workflow_run",
            resource_id=run.id,
            details={"workflow_id": workflow.id, "status": run.status, "steps": run.current_step},
        )
    )
    return run


async def cancel_workflow_run(
    session: AsyncSession,
    actor: UserRecord,
    run: WorkflowRun,
) -> WorkflowRun:
    if run.status not in {"queued", "running"}:
        raise ValueError("Only an active workflow run can be cancelled")
    run.status = "cancelled"
    run.cancelled_at = now()
    session.add(
        AuditEvent(
            organization_id=run.organization_id,
            user_id=actor.id,
            action="workflow.run.cancelled",
            resource_type="workflow_run",
            resource_id=run.id,
            details={"workflow_id": run.workflow_id},
        )
    )
    return run


async def generate_report_content(
    session: AsyncSession,
    actor: UserRecord,
    report: Report,
    *,
    audit: bool = True,
) -> Report:
    project: Project | None = None
    task_counts: dict[str, int] = {}
    events: list[ProjectEvent] = []
    if report.project_id:
        project = await session.scalar(
            select(Project).where(
                Project.id == report.project_id,
                Project.organization_id == report.organization_id,
            )
        )
        rows = (
            await session.execute(
                select(Task.status, func.count(Task.id))
                .where(Task.project_id == report.project_id, Task.status != "deleted")
                .group_by(Task.status)
            )
        ).all()
        task_counts = {str(name): int(count) for name, count in rows}
        events = await project_history(session, project, limit=50) if project else []
    content = {
        "schema_version": 1,
        "report_id": report.id,
        "organization_id": report.organization_id,
        "generated_by_id": actor.id,
        "generated_at": iso(now()),
        "type": report.type,
        "project": (
            {
                "id": project.id,
                "name": project.name,
                "status": project.status,
                "progress": project.progress,
                "risk": project.risk,
                "review_status": project.review_status,
            }
            if project
            else None
        ),
        "task_counts": task_counts,
        "metrics": report.metrics or {},
        "history": [project_event_snapshot(item) for item in events],
        "claim_boundary": "This report contains retained AIOS records only and makes no external provider claim.",
    }
    encoded = (json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    report.content = content
    report.checksum = hashlib.sha256(encoded).hexdigest()
    report.size_bytes = len(encoded)
    report.generated_by_id = actor.id
    report.status = "ready"
    report.version += 1
    if audit:
        session.add(
            AuditEvent(
                organization_id=report.organization_id,
                user_id=actor.id,
                action="report.generated",
                resource_type="report",
                resource_id=report.id,
                details={
                    "checksum": report.checksum,
                    "size_bytes": report.size_bytes,
                    "version": report.version,
                },
            )
        )
    return report
