"""Governed provider-neutral workforce and academy services for Phase 29F."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord
from app.db.models import (
    AcademyAssessment,
    AcademyCertification,
    AcademyCourse,
    AcademyEnrollment,
    AuditEvent,
    Project,
    Role,
    Task,
    User,
    WorkforceAssignment,
    WorkforceHealthReport,
    WorkforceIncident,
    WorkforceMember,
    WorkforcePerformanceEvent,
    uuid_str,
)

WORKER_STATES = frozenset(
    {"active", "supervised", "suspended", "retraining", "retired"}
)
ASSIGNMENT_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "start": (frozenset({"assigned", "queued", "rework", "blocked"}), "in_progress"),
    "submit_review": (frozenset({"in_progress", "rework"}), "review"),
    "approve": (frozenset({"review"}), "completed"),
    "rework": (frozenset({"review", "completed"}), "rework"),
    "block": (frozenset({"assigned", "in_progress", "review", "rework"}), "blocked"),
    "cancel": (frozenset({"assigned", "in_progress", "review", "rework", "blocked"}), "cancelled"),
    "reopen": (frozenset({"cancelled", "completed"}), "assigned"),
}


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def member_snapshot(
    item: WorkforceMember,
    *,
    performance: dict[str, float] | None = None,
    health: WorkforceHealthReport | None = None,
    success_count: int = 0,
    failure_count: int = 0,
) -> dict[str, Any]:
    performance = performance or {}
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "user_id": item.user_id,
        "manager_id": item.manager_id,
        "worker_key": item.worker_key,
        "kind": item.kind,
        "name": item.name,
        "role": item.role,
        "department": item.department,
        "ministry": item.ministry,
        "grade": item.grade,
        "status": item.status,
        "skills": item.skills,
        "certifications": item.certifications,
        "restrictions": item.restrictions,
        "warnings": item.warnings,
        "provider_neutral": item.provider_neutral,
        "metadata": item.profile_metadata,
        "version": item.version,
        "performance": performance.get("quality"),
        "reliability": performance.get("reliability"),
        "collaboration": health.collaboration if health else performance.get("collaboration"),
        "operational_health": health.operational_health if health else None,
        "trust": health.trust if health else performance.get("policy"),
        "learning": health.learning if health else performance.get("learning"),
        "recommendation": health.recommendation if health else None,
        "success_count": success_count,
        "failure_count": failure_count,
        "last_evaluated_at": iso(health.created_at) if health else None,
        "retired_at": iso(item.retired_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def assignment_snapshot(item: WorkforceAssignment) -> dict[str, Any]:
    required = set(item.acceptance_criteria or [])
    passed = set((item.evidence or {}).get("passed_criteria") or [])
    completeness = round(len(required & passed) / len(required), 4) if required else 0.0
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "project_id": item.project_id,
        "task_id": item.task_id,
        "worker_id": item.worker_id,
        "reviewer_id": item.reviewer_id,
        "title": item.title,
        "required_skills": item.required_skills,
        "acceptance_criteria": item.acceptance_criteria,
        "status": item.status,
        "priority": item.priority,
        "risk": item.risk,
        "evidence": item.evidence,
        "defects": item.defects,
        "attempts": item.attempts,
        "completeness": completeness,
        "version": item.version,
        "started_at": iso(item.started_at),
        "completed_at": iso(item.completed_at),
        "cancelled_at": iso(item.cancelled_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def performance_snapshot(item: WorkforcePerformanceEvent) -> dict[str, Any]:
    return {
        "id": item.id,
        "worker_id": item.worker_id,
        "assignment_id": item.assignment_id,
        "outcome": item.outcome,
        "quality_score": item.quality_score,
        "reliability_score": item.reliability_score,
        "collaboration_score": item.collaboration_score,
        "policy_score": item.policy_score,
        "learning_score": item.learning_score,
        "notes": item.notes,
        "created_by_id": item.created_by_id,
        "created_at": iso(item.created_at),
    }


def health_snapshot(item: WorkforceHealthReport) -> dict[str, Any]:
    return {
        "id": item.id,
        "worker_id": item.worker_id,
        "project_id": item.project_id,
        "operational_health": item.operational_health,
        "performance": item.performance,
        "collaboration": item.collaboration,
        "trust": item.trust,
        "learning": item.learning,
        "recommendation": item.recommendation,
        "restrictions": item.restrictions,
        "incidents": item.incidents,
        "generated_by_id": item.generated_by_id,
        "created_at": iso(item.created_at),
    }


def incident_snapshot(item: WorkforceIncident) -> dict[str, Any]:
    return {
        "id": item.id,
        "worker_id": item.worker_id,
        "assignment_id": item.assignment_id,
        "severity": item.severity,
        "category": item.category,
        "description": item.description,
        "status": item.status,
        "restrictions_applied": item.restrictions_applied,
        "opened_by_id": item.opened_by_id,
        "resolved_by_id": item.resolved_by_id,
        "resolved_at": iso(item.resolved_at),
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def course_snapshot(item: AcademyCourse) -> dict[str, Any]:
    return {
        "id": item.id,
        "organization_id": item.organization_id,
        "code": item.code,
        "title": item.title,
        "description": item.description,
        "competencies": item.competencies,
        "passing_score": item.passing_score,
        "status": item.status,
        "version": item.version,
        "created_by_id": item.created_by_id,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def enrollment_snapshot(item: AcademyEnrollment) -> dict[str, Any]:
    return {
        "id": item.id,
        "course_id": item.course_id,
        "worker_id": item.worker_id,
        "assigned_by_id": item.assigned_by_id,
        "status": item.status,
        "due_at": iso(item.due_at),
        "started_at": iso(item.started_at),
        "completed_at": iso(item.completed_at),
        "attempts": item.attempts,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


def assessment_snapshot(item: AcademyAssessment) -> dict[str, Any]:
    return {
        "id": item.id,
        "enrollment_id": item.enrollment_id,
        "course_id": item.course_id,
        "worker_id": item.worker_id,
        "assessed_by_id": item.assessed_by_id,
        "attempt_number": item.attempt_number,
        "score": item.score,
        "passed": item.passed,
        "evidence": item.evidence,
        "created_at": iso(item.created_at),
    }


def certification_snapshot(item: AcademyCertification) -> dict[str, Any]:
    return {
        "id": item.id,
        "worker_id": item.worker_id,
        "course_id": item.course_id,
        "assessment_id": item.assessment_id,
        "issued_by_id": item.issued_by_id,
        "code": item.code,
        "status": item.status,
        "issued_at": iso(item.issued_at),
        "expires_at": iso(item.expires_at),
        "revoked_at": iso(item.revoked_at),
        "metadata": item.certification_metadata,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }


async def ensure_user_member(
    session: AsyncSession, user: User, role_name: str | None = None
) -> WorkforceMember:
    key = f"user:{user.id}"
    item = await session.scalar(
        select(WorkforceMember).where(
            WorkforceMember.organization_id == user.organization_id,
            WorkforceMember.worker_key == key,
        )
    )
    if item is None:
        item = WorkforceMember(
            id=uuid_str(),
            organization_id=user.organization_id,
            user_id=user.id,
            worker_key=key,
            kind="human",
            name=user.name,
            role=role_name or "Member",
            department=role_name or "Unassigned",
            status="active" if user.status in {"active", "online"} else "supervised",
            skills=[],
            certifications=[],
            restrictions=[],
            warnings=[],
            provider_neutral=True,
            profile_metadata={"source": "user"},
        )
        session.add(item)
    else:
        item.name = user.name
        if role_name:
            item.role = role_name
            if item.department == "Unassigned":
                item.department = role_name
    return item


async def sync_human_workforce(
    session: AsyncSession, organization_id: str
) -> list[WorkforceMember]:
    rows = (
        await session.execute(
            select(User, Role.name)
            .outerjoin(Role, Role.id == User.role_id)
            .where(
                User.organization_id == organization_id,
                User.deleted_at.is_(None),
            )
            .order_by(User.name)
        )
    ).all()
    members: list[WorkforceMember] = []
    for user, role_name in rows:
        members.append(await ensure_user_member(session, user, role_name))
    await session.flush()
    return members


async def create_digital_member(
    session: AsyncSession,
    actor: UserRecord,
    *,
    name: str,
    role: str,
    department: str,
    ministry: str | None = None,
    manager_id: str | None = None,
    skills: Sequence[str] = (),
    grade: int = 1,
) -> WorkforceMember:
    normalized_name = name.strip()
    if len(normalized_name) < 2:
        raise ValueError("Workforce member name is invalid")
    if manager_id:
        manager = await session.scalar(
            select(WorkforceMember).where(
                WorkforceMember.id == manager_id,
                WorkforceMember.organization_id == actor.organization_id,
                WorkforceMember.status.notin_({"retired"}),
            )
        )
        if manager is None:
            raise LookupError("Workforce manager not found")
    base = hashlib.sha256(
        f"{actor.organization_id}:{normalized_name}:{role}:{department}".encode()
    ).hexdigest()[:16]
    key = f"digital:{base}"
    existing = await session.scalar(
        select(WorkforceMember).where(
            WorkforceMember.organization_id == actor.organization_id,
            WorkforceMember.worker_key == key,
        )
    )
    if existing is not None:
        raise ValueError("A matching digital workforce member already exists")
    item = WorkforceMember(
        id=uuid_str(),
        organization_id=actor.organization_id,
        manager_id=manager_id,
        worker_key=key,
        kind="digital",
        name=normalized_name,
        role=role.strip() or "Digital Worker",
        department=department.strip() or "Unassigned",
        ministry=(ministry or "").strip() or None,
        grade=max(1, min(100, grade)),
        status="active",
        skills=sorted({value.strip() for value in skills if value.strip()}),
        certifications=[],
        restrictions=[],
        warnings=[],
        provider_neutral=True,
        profile_metadata={
            "provider_activation": "deferred_to_29J",
            "execution_mode": "provider-neutral",
        },
    )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="workforce.member.created",
            resource_type="workforce_member",
            resource_id=item.id,
            details={"kind": "digital", "provider_neutral": True, "role": item.role},
        )
    )
    await session.flush()
    return item


async def member_metrics(
    session: AsyncSession, member_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {value: {} for value in member_ids}
    if not member_ids:
        return result
    performance_rows = (
        await session.execute(
            select(
                WorkforcePerformanceEvent.worker_id,
                func.avg(WorkforcePerformanceEvent.quality_score),
                func.avg(WorkforcePerformanceEvent.reliability_score),
                func.avg(WorkforcePerformanceEvent.collaboration_score),
                func.avg(WorkforcePerformanceEvent.policy_score),
                func.avg(WorkforcePerformanceEvent.learning_score),
                func.count(WorkforcePerformanceEvent.id).filter(WorkforcePerformanceEvent.outcome == "success"),
                func.count(WorkforcePerformanceEvent.id).filter(WorkforcePerformanceEvent.outcome == "failure"),
            )
            .where(WorkforcePerformanceEvent.worker_id.in_(list(member_ids)))
            .group_by(WorkforcePerformanceEvent.worker_id)
        )
    ).all()
    for row in performance_rows:
        result[row[0]].update(
            {
                "performance": {
                    "quality": float(row[1] or 0),
                    "reliability": float(row[2] or 0),
                    "collaboration": float(row[3] or 0),
                    "policy": float(row[4] or 0),
                    "learning": float(row[5] or 0),
                },
                "success_count": int(row[6] or 0),
                "failure_count": int(row[7] or 0),
            }
        )
    health_rows = list(
        (
            await session.scalars(
                select(WorkforceHealthReport)
                .where(WorkforceHealthReport.worker_id.in_(list(member_ids)))
                .order_by(WorkforceHealthReport.worker_id, WorkforceHealthReport.created_at.desc())
            )
        ).all()
    )
    for health in health_rows:
        result[health.worker_id].setdefault("health", health)
    return result


async def transition_member(
    session: AsyncSession,
    actor: UserRecord,
    member: WorkforceMember,
    *,
    action: str,
    reason: str = "",
    grade: int | None = None,
) -> WorkforceMember:
    normalized = action.strip().lower()
    previous = member.status
    if normalized == "promote":
        if member.status not in {"active", "supervised"}:
            raise ValueError("Only active or supervised members can be promoted")
        member.grade = max(member.grade + 1, grade or 0)
    elif normalized == "suspend":
        if member.status in {"retired", "suspended"}:
            raise ValueError("Workforce member cannot be suspended from this state")
        member.status = "suspended"
    elif normalized == "restore":
        if member.status not in {"suspended", "supervised", "retraining"}:
            raise ValueError("Workforce member cannot be restored from this state")
        member.status = "active"
    elif normalized == "supervise":
        if member.status == "retired":
            raise ValueError("Retired workforce member cannot be supervised")
        member.status = "supervised"
    elif normalized == "retrain":
        if member.status == "retired":
            raise ValueError("Retired workforce member cannot be retrained")
        member.status = "retraining"
    elif normalized == "retire":
        if member.status == "retired":
            return member
        active = int(
            await session.scalar(
                select(func.count(WorkforceAssignment.id)).where(
                    WorkforceAssignment.worker_id == member.id,
                    WorkforceAssignment.status.in_({"assigned", "in_progress", "review", "rework", "blocked"}),
                )
            )
            or 0
        )
        if active:
            raise ValueError("Workforce member has active assignments")
        member.status = "retired"
        member.retired_at = now()
    else:
        raise ValueError("Unsupported workforce lifecycle action")
    member.version += 1
    session.add(
        AuditEvent(
            organization_id=member.organization_id,
            user_id=actor.id,
            action=f"workforce.member.{normalized}",
            resource_type="workforce_member",
            resource_id=member.id,
            details={
                "from": previous,
                "to": member.status,
                "grade": member.grade,
                "reason": reason.strip() or None,
            },
        )
    )
    return member


async def create_assignment(
    session: AsyncSession,
    actor: UserRecord,
    *,
    project_id: str,
    worker_id: str,
    title: str,
    task_id: str | None = None,
    reviewer_id: str | None = None,
    required_skills: Sequence[str] = (),
    acceptance_criteria: Sequence[str] = (),
    priority: int = 50,
    risk: str = "normal",
) -> WorkforceAssignment:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.organization_id == actor.organization_id,
            Project.status.notin_({"deleted", "archived", "cancelled"}),
        )
    )
    if project is None:
        raise LookupError("Assignment project not found")
    worker = await session.scalar(
        select(WorkforceMember).where(
            WorkforceMember.id == worker_id,
            WorkforceMember.organization_id == actor.organization_id,
            WorkforceMember.status.in_({"active", "supervised", "retraining"}),
        )
    )
    if worker is None:
        raise LookupError("Assignable workforce member not found")
    task: Task | None = None
    if task_id:
        task = await session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.organization_id == actor.organization_id,
                Task.project_id == project.id,
                Task.status != "deleted",
            )
        )
        if task is None:
            raise LookupError("Assignment task not found")
    if reviewer_id:
        reviewer = await session.scalar(
            select(WorkforceMember).where(
                WorkforceMember.id == reviewer_id,
                WorkforceMember.organization_id == actor.organization_id,
                WorkforceMember.status.in_({"active", "supervised"}),
            )
        )
        if reviewer is None:
            raise LookupError("Assignment reviewer not found")
        if reviewer.id == worker.id:
            raise ValueError("Assignment reviewer must differ from the worker")
    missing = sorted(set(required_skills) - set(worker.skills or []))
    assignment = WorkforceAssignment(
        id=uuid_str(),
        organization_id=actor.organization_id,
        project_id=project.id,
        task_id=task.id if task else None,
        worker_id=worker.id,
        reviewer_id=reviewer_id,
        title=title.strip(),
        required_skills=sorted(set(required_skills)),
        acceptance_criteria=list(dict.fromkeys(value.strip() for value in acceptance_criteria if value.strip())),
        status="assigned" if not missing else "blocked",
        priority=max(1, min(100, priority)),
        risk=risk,
        evidence={"passed_criteria": [], "missing_skills": missing},
        defects=[],
        attempts=0,
        version=1,
    )
    session.add(assignment)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="workforce.assignment.created",
            resource_type="workforce_assignment",
            resource_id=assignment.id,
            details={"project_id": project.id, "worker_id": worker.id, "missing_skills": missing},
        )
    )
    await session.flush()
    return assignment


async def transition_assignment(
    session: AsyncSession,
    actor: UserRecord,
    assignment: WorkforceAssignment,
    *,
    action: str,
    evidence: dict[str, Any] | None = None,
    defects: Sequence[str] = (),
    reason: str = "",
) -> WorkforceAssignment:
    normalized = action.strip().lower()
    transition = ASSIGNMENT_TRANSITIONS.get(normalized)
    if transition is None:
        raise ValueError("Unsupported assignment transition")
    allowed, target = transition
    if assignment.status not in allowed:
        raise ValueError(f"Assignment cannot {normalized} from status {assignment.status}")
    previous = assignment.status
    current = now()
    assignment.status = target
    assignment.version += 1
    if normalized == "start":
        assignment.started_at = assignment.started_at or current
        assignment.attempts += 1
    if evidence is not None:
        assignment.evidence = {**(assignment.evidence or {}), **evidence}
    if defects:
        assignment.defects = list(dict.fromkeys([*(assignment.defects or []), *defects]))
    if normalized == "submit_review":
        required = set(assignment.acceptance_criteria or [])
        passed = set((assignment.evidence or {}).get("passed_criteria") or [])
        if required and not required.issubset(passed):
            raise ValueError("Assignment evidence does not satisfy all acceptance criteria")
    elif normalized == "approve":
        assignment.completed_at = current
    elif normalized == "rework":
        assignment.completed_at = None
        assignment.attempts += 1
    elif normalized == "cancel":
        assignment.cancelled_at = current
    elif normalized == "reopen":
        assignment.cancelled_at = None
        assignment.completed_at = None
    session.add(
        AuditEvent(
            organization_id=assignment.organization_id,
            user_id=actor.id,
            action=f"workforce.assignment.{normalized}",
            resource_type="workforce_assignment",
            resource_id=assignment.id,
            details={"from": previous, "to": target, "reason": reason.strip() or None, "version": assignment.version},
        )
    )
    return assignment


async def record_performance(
    session: AsyncSession,
    actor: UserRecord,
    member: WorkforceMember,
    *,
    assignment_id: str | None,
    outcome: str,
    quality: float,
    reliability: float,
    collaboration: float,
    policy: float,
    learning: float,
    notes: str = "",
) -> WorkforcePerformanceEvent:
    values = [quality, reliability, collaboration, policy, learning]
    if any(value < 0 or value > 100 for value in values):
        raise ValueError("Performance scores must be between 0 and 100")
    if outcome not in {"success", "failure", "partial"}:
        raise ValueError("Unsupported performance outcome")
    if assignment_id:
        assignment = await session.scalar(
            select(WorkforceAssignment).where(
                WorkforceAssignment.id == assignment_id,
                WorkforceAssignment.organization_id == actor.organization_id,
                WorkforceAssignment.worker_id == member.id,
            )
        )
        if assignment is None:
            raise LookupError("Workforce assignment not found")
    item = WorkforcePerformanceEvent(
        id=uuid_str(),
        organization_id=actor.organization_id,
        worker_id=member.id,
        assignment_id=assignment_id,
        outcome=outcome,
        quality_score=quality,
        reliability_score=reliability,
        collaboration_score=collaboration,
        policy_score=policy,
        learning_score=learning,
        notes=notes.strip() or None,
        created_by_id=actor.id,
        created_at=now(),
    )
    session.add(item)
    if outcome == "failure":
        member.warnings = [*(member.warnings or []), f"Performance failure recorded {iso(item.created_at)}"][-20:]
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="workforce.performance.recorded",
            resource_type="workforce_member",
            resource_id=member.id,
            details={"performance_event_id": item.id, "outcome": outcome, "quality": quality},
        )
    )
    return item


async def generate_health_report(
    session: AsyncSession,
    actor: UserRecord,
    member: WorkforceMember,
    *,
    project_id: str | None = None,
) -> WorkforceHealthReport:
    statement = select(
        func.avg(WorkforcePerformanceEvent.quality_score),
        func.avg(WorkforcePerformanceEvent.reliability_score),
        func.avg(WorkforcePerformanceEvent.collaboration_score),
        func.avg(WorkforcePerformanceEvent.policy_score),
        func.avg(WorkforcePerformanceEvent.learning_score),
    ).where(WorkforcePerformanceEvent.worker_id == member.id)
    averages = (await session.execute(statement)).one()
    quality = float(averages[0] or 50)
    reliability = float(averages[1] or 50)
    collaboration = float(averages[2] or 50)
    policy = float(averages[3] or 50)
    learning = float(averages[4] or 50)
    open_incidents = list(
        (
            await session.scalars(
                select(WorkforceIncident).where(
                    WorkforceIncident.worker_id == member.id,
                    WorkforceIncident.status != "resolved",
                )
            )
        ).all()
    )
    incident_penalty = min(40.0, sum(20 if item.severity == "critical" else 10 if item.severity == "high" else 5 for item in open_incidents))
    operational = max(0.0, round((quality + reliability + policy) / 3 - incident_penalty, 2))
    trust = max(0.0, round((reliability + policy) / 2 - incident_penalty / 2, 2))
    performance = round((quality + reliability) / 2, 2)
    restrictions: list[str] = []
    if operational < 40 or trust < 40:
        recommendation = "suspend"
        restrictions = ["privileged_work", "unsupervised_execution"]
    elif operational < 65 or open_incidents:
        recommendation = "supervise"
        restrictions = ["unsupervised_execution"]
    elif learning < 60:
        recommendation = "retrain"
        restrictions = []
    else:
        recommendation = "healthy"
    report = WorkforceHealthReport(
        id=uuid_str(),
        organization_id=actor.organization_id,
        worker_id=member.id,
        project_id=project_id,
        operational_health=operational,
        performance=performance,
        collaboration=round(collaboration, 2),
        trust=trust,
        learning=round(learning, 2),
        recommendation=recommendation,
        restrictions=restrictions,
        incidents=[item.id for item in open_incidents],
        generated_by_id=actor.id,
        created_at=now(),
    )
    session.add(report)
    member.restrictions = restrictions
    if recommendation == "suspend" and member.status != "retired":
        member.status = "suspended"
    elif recommendation == "supervise" and member.status == "active":
        member.status = "supervised"
    elif recommendation == "retrain" and member.status == "active":
        member.status = "retraining"
    member.version += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="workforce.health.generated",
            resource_type="workforce_member",
            resource_id=member.id,
            details={"report_id": report.id, "recommendation": recommendation, "operational_health": operational},
        )
    )
    return report


async def create_incident(
    session: AsyncSession,
    actor: UserRecord,
    member: WorkforceMember,
    *,
    severity: str,
    category: str,
    description: str,
    assignment_id: str | None = None,
    restrictions: Sequence[str] = (),
) -> WorkforceIncident:
    if severity not in {"low", "medium", "high", "critical"}:
        raise ValueError("Unsupported workforce incident severity")
    if assignment_id:
        assignment = await session.scalar(
            select(WorkforceAssignment).where(
                WorkforceAssignment.id == assignment_id,
                WorkforceAssignment.worker_id == member.id,
                WorkforceAssignment.organization_id == actor.organization_id,
            )
        )
        if assignment is None:
            raise LookupError("Workforce assignment not found")
    incident = WorkforceIncident(
        id=uuid_str(),
        organization_id=actor.organization_id,
        worker_id=member.id,
        assignment_id=assignment_id,
        severity=severity,
        category=category.strip().lower(),
        description=description.strip(),
        status="open",
        restrictions_applied=list(dict.fromkeys(restrictions)),
        opened_by_id=actor.id,
    )
    session.add(incident)
    if restrictions:
        member.restrictions = list(dict.fromkeys([*(member.restrictions or []), *restrictions]))
    if severity == "critical" and member.status != "retired":
        member.status = "suspended"
    elif severity == "high" and member.status == "active":
        member.status = "supervised"
    member.version += 1
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="workforce.incident.created",
            resource_type="workforce_incident",
            resource_id=incident.id,
            details={"worker_id": member.id, "severity": severity, "restrictions": list(restrictions)},
        )
    )
    return incident


async def resolve_incident(
    session: AsyncSession,
    actor: UserRecord,
    incident: WorkforceIncident,
    *,
    note: str = "",
) -> WorkforceIncident:
    if incident.status == "resolved":
        return incident
    incident.status = "resolved"
    incident.resolved_by_id = actor.id
    incident.resolved_at = now()
    session.add(
        AuditEvent(
            organization_id=incident.organization_id,
            user_id=actor.id,
            action="workforce.incident.resolved",
            resource_type="workforce_incident",
            resource_id=incident.id,
            details={"worker_id": incident.worker_id, "note": note.strip() or None},
        )
    )
    return incident


async def create_course(
    session: AsyncSession,
    actor: UserRecord,
    *,
    code: str,
    title: str,
    description: str | None,
    competencies: Sequence[str],
    passing_score: float,
) -> AcademyCourse:
    normalized_code = "-".join(code.strip().upper().split())
    if len(normalized_code) < 2:
        raise ValueError("Course code is invalid")
    existing = await session.scalar(
        select(AcademyCourse).where(
            AcademyCourse.organization_id == actor.organization_id,
            AcademyCourse.code == normalized_code,
        )
    )
    if existing is not None:
        raise ValueError("Course code already exists")
    if passing_score < 0 or passing_score > 100:
        raise ValueError("Passing score must be between 0 and 100")
    item = AcademyCourse(
        id=uuid_str(),
        organization_id=actor.organization_id,
        code=normalized_code,
        title=title.strip(),
        description=(description or "").strip() or None,
        competencies=list(dict.fromkeys(value.strip() for value in competencies if value.strip())),
        passing_score=passing_score,
        status="active",
        version=1,
        created_by_id=actor.id,
    )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="academy.course.created",
            resource_type="academy_course",
            resource_id=item.id,
            details={"code": item.code, "passing_score": passing_score},
        )
    )
    await session.flush()
    return item


async def enroll_member(
    session: AsyncSession,
    actor: UserRecord,
    course: AcademyCourse,
    member: WorkforceMember,
    *,
    due_at: datetime | None = None,
) -> AcademyEnrollment:
    if course.status != "active":
        raise ValueError("Course is not active")
    existing = await session.scalar(
        select(AcademyEnrollment).where(
            AcademyEnrollment.course_id == course.id,
            AcademyEnrollment.worker_id == member.id,
            AcademyEnrollment.status.in_({"assigned", "in_progress"}),
        )
    )
    if existing is not None:
        return existing
    item = AcademyEnrollment(
        id=uuid_str(),
        organization_id=actor.organization_id,
        course_id=course.id,
        worker_id=member.id,
        assigned_by_id=actor.id,
        status="assigned",
        due_at=due_at,
        attempts=0,
    )
    session.add(item)
    session.add(
        AuditEvent(
            organization_id=actor.organization_id,
            user_id=actor.id,
            action="academy.enrollment.created",
            resource_type="academy_enrollment",
            resource_id=item.id,
            details={"course_id": course.id, "worker_id": member.id},
        )
    )
    await session.flush()
    return item


async def assess_enrollment(
    session: AsyncSession,
    actor: UserRecord,
    enrollment: AcademyEnrollment,
    *,
    score: float,
    evidence: dict[str, Any] | None = None,
) -> tuple[AcademyAssessment, AcademyCertification | None]:
    if enrollment.status in {"cancelled"}:
        raise ValueError("Cancelled enrollment cannot be assessed")
    if score < 0 or score > 100:
        raise ValueError("Assessment score must be between 0 and 100")
    course = await session.get(AcademyCourse, enrollment.course_id)
    member = await session.get(WorkforceMember, enrollment.worker_id)
    if course is None or member is None:
        raise LookupError("Academy enrollment dependencies are unavailable")
    enrollment.attempts += 1
    enrollment.started_at = enrollment.started_at or now()
    passed = score >= course.passing_score
    assessment = AcademyAssessment(
        id=uuid_str(),
        organization_id=enrollment.organization_id,
        enrollment_id=enrollment.id,
        course_id=course.id,
        worker_id=member.id,
        assessed_by_id=actor.id,
        attempt_number=enrollment.attempts,
        score=score,
        passed=passed,
        evidence=evidence or {},
        created_at=now(),
    )
    session.add(assessment)
    await session.flush()
    certification: AcademyCertification | None = None
    if passed:
        enrollment.status = "completed"
        enrollment.completed_at = now()
        code = f"AIOS-{course.code}-{member.id[:8]}-{assessment.id[:8]}"
        certification = AcademyCertification(
            id=uuid_str(),
            organization_id=enrollment.organization_id,
            worker_id=member.id,
            course_id=course.id,
            assessment_id=assessment.id,
            issued_by_id=actor.id,
            code=code,
            status="active",
            issued_at=now(),
            certification_metadata={"score": score, "course_version": course.version},
        )
        session.add(certification)
        member.certifications = list(dict.fromkeys([*(member.certifications or []), course.code]))
        member.skills = list(dict.fromkeys([*(member.skills or []), *(course.competencies or [])]))
        if member.status == "retraining":
            member.status = "active"
        member.version += 1
    else:
        enrollment.status = "in_progress"
        if enrollment.attempts >= 3 and member.status != "retired":
            member.status = "supervised"
            member.warnings = [*(member.warnings or []), f"Failed {course.code} assessment {enrollment.attempts} times"][-20:]
            member.version += 1
    session.add(
        AuditEvent(
            organization_id=enrollment.organization_id,
            user_id=actor.id,
            action="academy.assessment.recorded",
            resource_type="academy_enrollment",
            resource_id=enrollment.id,
            details={"assessment_id": assessment.id, "score": score, "passed": passed, "certification_id": certification.id if certification else None},
        )
    )
    return assessment, certification


async def revoke_certification(
    session: AsyncSession,
    actor: UserRecord,
    certification: AcademyCertification,
    *,
    reason: str,
) -> AcademyCertification:
    if certification.status == "revoked":
        return certification
    certification.status = "revoked"
    certification.revoked_at = now()
    certification.certification_metadata = {
        **(certification.certification_metadata or {}),
        "revocation_reason": reason.strip(),
    }
    course = await session.get(AcademyCourse, certification.course_id)
    member = await session.get(WorkforceMember, certification.worker_id)
    if course is not None and member is not None:
        member.certifications = [value for value in member.certifications or [] if value != course.code]
        member.version += 1
    session.add(
        AuditEvent(
            organization_id=certification.organization_id,
            user_id=actor.id,
            action="academy.certification.revoked",
            resource_type="academy_certification",
            resource_id=certification.id,
            details={"reason_present": bool(reason.strip())},
        )
    )
    return certification
