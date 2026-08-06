"""Tenant-scoped governed workforce APIs for Phase 29F."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import (
    AcademyCertification,
    AcademyEnrollment,
    WorkforceAssignment,
    WorkforceHealthReport,
    WorkforceIncident,
    WorkforceMember,
    WorkforcePerformanceEvent,
)
from app.services import workforce

router = APIRouter()


class DigitalMemberCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    role: str = Field(default="Digital Worker", min_length=2, max_length=120)
    department: str = Field(default="Unassigned", min_length=2, max_length=120)
    ministry: str | None = Field(default=None, max_length=160)
    manager_id: str | None = None
    skills: list[str] = Field(default_factory=list, max_length=100)
    grade: int = Field(default=1, ge=1, le=100)


class MemberLifecycle(BaseModel):
    action: Literal["promote", "suspend", "restore", "supervise", "retrain", "retire"]
    reason: str = Field(default="", max_length=2000)
    grade: int | None = Field(default=None, ge=1, le=100)


class AssignmentCreate(BaseModel):
    project_id: str
    worker_id: str
    title: str = Field(min_length=2, max_length=300)
    task_id: str | None = None
    reviewer_id: str | None = None
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=100)
    priority: int = Field(default=50, ge=1, le=100)
    risk: Literal["low", "normal", "high", "critical"] = "normal"


class AssignmentTransition(BaseModel):
    action: Literal["start", "submit_review", "approve", "rework", "block", "cancel", "reopen"]
    evidence: dict[str, Any] = Field(default_factory=dict)
    defects: list[str] = Field(default_factory=list, max_length=100)
    reason: str = Field(default="", max_length=2000)


class PerformanceCreate(BaseModel):
    assignment_id: str | None = None
    outcome: Literal["success", "failure", "partial"]
    quality: float = Field(ge=0, le=100)
    reliability: float = Field(ge=0, le=100)
    collaboration: float = Field(ge=0, le=100)
    policy: float = Field(ge=0, le=100)
    learning: float = Field(ge=0, le=100)
    notes: str = Field(default="", max_length=5000)


class HealthRequest(BaseModel):
    project_id: str | None = None


class IncidentCreate(BaseModel):
    worker_id: str
    assignment_id: str | None = None
    severity: Literal["low", "medium", "high", "critical"]
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2, max_length=10000)
    restrictions: list[str] = Field(default_factory=list, max_length=100)


class IncidentResolve(BaseModel):
    note: str = Field(default="", max_length=5000)


async def _member(
    session: AsyncSession,
    actor: UserRecord,
    member_id: str,
    *,
    for_update: bool = False,
) -> WorkforceMember:
    statement = select(WorkforceMember).where(
        WorkforceMember.id == member_id,
        WorkforceMember.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Workforce member not found")
    return item


async def _assignment(
    session: AsyncSession,
    actor: UserRecord,
    assignment_id: str,
    *,
    for_update: bool = False,
) -> WorkforceAssignment:
    statement = select(WorkforceAssignment).where(
        WorkforceAssignment.id == assignment_id,
        WorkforceAssignment.organization_id == actor.organization_id,
    )
    if for_update:
        statement = statement.with_for_update()
    item = await session.scalar(statement)
    if item is None:
        raise HTTPException(status_code=404, detail="Workforce assignment not found")
    return item


@router.get("/members")
async def list_members(
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    kind: str | None = Query(default=None, max_length=32),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("workforce:read")),
    session: AsyncSession = Depends(get_db),
):
    await workforce.sync_human_workforce(session, actor.organization_id)
    await session.commit()
    statement = select(WorkforceMember).where(
        WorkforceMember.organization_id == actor.organization_id
    )
    if status_filter:
        statement = statement.where(WorkforceMember.status == status_filter)
    if kind:
        statement = statement.where(WorkforceMember.kind == kind)
    if search:
        normalized = search.strip()
        statement = statement.where(
            WorkforceMember.name.ilike(f"%{normalized}%")
            | WorkforceMember.role.ilike(f"%{normalized}%")
            | WorkforceMember.department.ilike(f"%{normalized}%")
        )
    items = list(
        (
            await session.scalars(
                statement.order_by(WorkforceMember.kind, WorkforceMember.name).limit(limit)
            )
        ).all()
    )
    metrics = await workforce.member_metrics(session, [item.id for item in items])
    return [
        workforce.member_snapshot(
            item,
            performance=metrics.get(item.id, {}).get("performance"),
            health=metrics.get(item.id, {}).get("health"),
            success_count=metrics.get(item.id, {}).get("success_count", 0),
            failure_count=metrics.get(item.id, {}).get("failure_count", 0),
        )
        for item in items
    ]


@router.post("/members", status_code=status.HTTP_201_CREATED)
async def create_member(
    data: DigitalMemberCreate,
    actor: UserRecord = Depends(require_permissions("workforce:manage")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await workforce.create_digital_member(
            session,
            actor,
            name=data.name,
            role=data.role,
            department=data.department,
            ministry=data.ministry,
            manager_id=data.manager_id,
            skills=data.skills,
            grade=data.grade,
        )
        await session.commit()
        await session.refresh(item)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workforce.member_snapshot(item)


@router.get("/members/{member_id}")
async def get_member(
    member_id: str,
    actor: UserRecord = Depends(require_permissions("workforce:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await _member(session, actor, member_id)
    metrics = await workforce.member_metrics(session, [item.id])
    current = metrics.get(item.id, {})
    return workforce.member_snapshot(
        item,
        performance=current.get("performance"),
        health=current.get("health"),
        success_count=current.get("success_count", 0),
        failure_count=current.get("failure_count", 0),
    )


@router.patch("/members/{member_id}/lifecycle")
async def update_member_lifecycle(
    member_id: str,
    data: MemberLifecycle,
    actor: UserRecord = Depends(require_permissions("workforce:manage")),
    session: AsyncSession = Depends(get_db),
):
    item = await _member(session, actor, member_id, for_update=True)
    try:
        await workforce.transition_member(
            session,
            actor,
            item,
            action=data.action,
            reason=data.reason,
            grade=data.grade,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return workforce.member_snapshot(item)


@router.get("/members/{member_id}/history")
async def member_history(
    member_id: str,
    actor: UserRecord = Depends(require_permissions("workforce:read")),
    session: AsyncSession = Depends(get_db),
):
    item = await _member(session, actor, member_id)
    assignments = list(
        (
            await session.scalars(
                select(WorkforceAssignment)
                .where(WorkforceAssignment.worker_id == item.id)
                .order_by(WorkforceAssignment.created_at.desc())
                .limit(200)
            )
        ).all()
    )
    performance = list(
        (
            await session.scalars(
                select(WorkforcePerformanceEvent)
                .where(WorkforcePerformanceEvent.worker_id == item.id)
                .order_by(WorkforcePerformanceEvent.created_at.desc())
                .limit(200)
            )
        ).all()
    )
    health = list(
        (
            await session.scalars(
                select(WorkforceHealthReport)
                .where(WorkforceHealthReport.worker_id == item.id)
                .order_by(WorkforceHealthReport.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    incidents = list(
        (
            await session.scalars(
                select(WorkforceIncident)
                .where(WorkforceIncident.worker_id == item.id)
                .order_by(WorkforceIncident.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    enrollments = list(
        (
            await session.scalars(
                select(AcademyEnrollment)
                .where(AcademyEnrollment.worker_id == item.id)
                .order_by(AcademyEnrollment.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    certifications = list(
        (
            await session.scalars(
                select(AcademyCertification)
                .where(AcademyCertification.worker_id == item.id)
                .order_by(AcademyCertification.issued_at.desc())
                .limit(100)
            )
        ).all()
    )
    return {
        "member": workforce.member_snapshot(item),
        "assignments": [workforce.assignment_snapshot(value) for value in assignments],
        "performance": [workforce.performance_snapshot(value) for value in performance],
        "health": [workforce.health_snapshot(value) for value in health],
        "incidents": [workforce.incident_snapshot(value) for value in incidents],
        "enrollments": [workforce.enrollment_snapshot(value) for value in enrollments],
        "certifications": [workforce.certification_snapshot(value) for value in certifications],
    }


@router.get("/assignments")
async def list_assignments(
    project_id: str | None = None,
    worker_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("workforce:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(WorkforceAssignment).where(
        WorkforceAssignment.organization_id == actor.organization_id
    )
    if project_id:
        statement = statement.where(WorkforceAssignment.project_id == project_id)
    if worker_id:
        statement = statement.where(WorkforceAssignment.worker_id == worker_id)
    if status_filter:
        statement = statement.where(WorkforceAssignment.status == status_filter)
    rows = list(
        (
            await session.scalars(
                statement.order_by(WorkforceAssignment.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [workforce.assignment_snapshot(item) for item in rows]


@router.post("/assignments", status_code=status.HTTP_201_CREATED)
async def create_assignment(
    data: AssignmentCreate,
    actor: UserRecord = Depends(require_permissions("workforce:write")),
    session: AsyncSession = Depends(get_db),
):
    try:
        item = await workforce.create_assignment(
            session,
            actor,
            project_id=data.project_id,
            worker_id=data.worker_id,
            title=data.title,
            task_id=data.task_id,
            reviewer_id=data.reviewer_id,
            required_skills=data.required_skills,
            acceptance_criteria=data.acceptance_criteria,
            priority=data.priority,
            risk=data.risk,
        )
        await session.commit()
        await session.refresh(item)
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workforce.assignment_snapshot(item)


@router.get("/assignments/{assignment_id}")
async def get_assignment(
    assignment_id: str,
    actor: UserRecord = Depends(require_permissions("workforce:read")),
    session: AsyncSession = Depends(get_db),
):
    return workforce.assignment_snapshot(await _assignment(session, actor, assignment_id))


@router.post("/assignments/{assignment_id}/transition")
async def transition_assignment(
    assignment_id: str,
    data: AssignmentTransition,
    actor: UserRecord = Depends(require_permissions("workforce:write")),
    session: AsyncSession = Depends(get_db),
):
    item = await _assignment(session, actor, assignment_id, for_update=True)
    try:
        await workforce.transition_assignment(
            session,
            actor,
            item,
            action=data.action,
            evidence=data.evidence,
            defects=data.defects,
            reason=data.reason,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return workforce.assignment_snapshot(item)


@router.post("/members/{member_id}/performance", status_code=status.HTTP_201_CREATED)
async def record_performance(
    member_id: str,
    data: PerformanceCreate,
    actor: UserRecord = Depends(require_permissions("workforce:manage")),
    session: AsyncSession = Depends(get_db),
):
    item = await _member(session, actor, member_id, for_update=True)
    try:
        record = await workforce.record_performance(
            session,
            actor,
            item,
            assignment_id=data.assignment_id,
            outcome=data.outcome,
            quality=data.quality,
            reliability=data.reliability,
            collaboration=data.collaboration,
            policy=data.policy,
            learning=data.learning,
            notes=data.notes,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workforce.performance_snapshot(record)


@router.post("/members/{member_id}/health", status_code=status.HTTP_201_CREATED)
async def generate_health(
    member_id: str,
    data: HealthRequest,
    actor: UserRecord = Depends(require_permissions("workforce:manage")),
    session: AsyncSession = Depends(get_db),
):
    item = await _member(session, actor, member_id, for_update=True)
    report = await workforce.generate_health_report(
        session, actor, item, project_id=data.project_id
    )
    await session.commit()
    return workforce.health_snapshot(report)


@router.get("/incidents")
async def list_incidents(
    worker_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: UserRecord = Depends(require_permissions("workforce:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = select(WorkforceIncident).where(
        WorkforceIncident.organization_id == actor.organization_id
    )
    if worker_id:
        statement = statement.where(WorkforceIncident.worker_id == worker_id)
    if status_filter:
        statement = statement.where(WorkforceIncident.status == status_filter)
    rows = list(
        (
            await session.scalars(
                statement.order_by(WorkforceIncident.created_at.desc()).limit(limit)
            )
        ).all()
    )
    return [workforce.incident_snapshot(item) for item in rows]


@router.post("/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(
    data: IncidentCreate,
    actor: UserRecord = Depends(require_permissions("workforce:manage")),
    session: AsyncSession = Depends(get_db),
):
    member = await _member(session, actor, data.worker_id, for_update=True)
    try:
        item = await workforce.create_incident(
            session,
            actor,
            member,
            severity=data.severity,
            category=data.category,
            description=data.description,
            assignment_id=data.assignment_id,
            restrictions=data.restrictions,
        )
        await session.commit()
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return workforce.incident_snapshot(item)


@router.post("/incidents/{incident_id}/resolve")
async def resolve_incident(
    incident_id: str,
    data: IncidentResolve,
    actor: UserRecord = Depends(require_permissions("workforce:manage")),
    session: AsyncSession = Depends(get_db),
):
    item = await session.scalar(
        select(WorkforceIncident)
        .where(
            WorkforceIncident.id == incident_id,
            WorkforceIncident.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Workforce incident not found")
    await workforce.resolve_incident(session, actor, item, note=data.note)
    await session.commit()
    return workforce.incident_snapshot(item)
