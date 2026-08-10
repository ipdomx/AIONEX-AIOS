"""Tenant-scoped global search across durable provider-neutral resources."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import UserRecord, current_user
from app.db.base import get_db
from app.db.models import (
    KnowledgeItem,
    Lesson,
    Project,
    Report,
    Task,
    Workflow,
    WorkforceMember,
)

router = APIRouter()


def _result(
    identifier: str,
    kind: str,
    title: str,
    subtitle: str,
    url: str,
    *,
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "id": identifier,
        "type": kind,
        "title": title,
        "subtitle": subtitle,
        "url": url,
        "status": status,
    }


@router.get("")
async def global_search(
    q: str = Query(..., min_length=1, max_length=300),
    type: str = Query("all", max_length=40),
    limit: int = Query(20, ge=1, le=100),
    actor: UserRecord = Depends(current_user),
    session: AsyncSession = Depends(get_db),
):
    normalized = q.strip()
    kinds = {
        "project",
        "task",
        "workflow",
        "report",
        "knowledge",
        "lesson",
        "workforce",
    }
    selected = kinds if type == "all" else ({type} if type in kinds else set())
    results: list[dict[str, Any]] = []

    if "project" in selected:
        project_rows = list(
            (
                await session.scalars(
                    select(Project)
                    .where(
                        Project.organization_id == actor.organization_id,
                        Project.status != "deleted",
                        or_(
                            Project.name.ilike(f"%{normalized}%"),
                            Project.description.ilike(f"%{normalized}%"),
                        ),
                    )
                    .order_by(Project.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        results.extend(
            _result(
                item.id,
                "project",
                item.name,
                item.description or item.status,
                f"/projects?project={item.id}",
                status=item.status,
            )
            for item in project_rows
        )

    if "task" in selected:
        task_rows = list(
            (
                await session.scalars(
                    select(Task)
                    .where(
                        Task.organization_id == actor.organization_id,
                        Task.status != "deleted",
                        or_(
                            Task.title.ilike(f"%{normalized}%"),
                            Task.description.ilike(f"%{normalized}%"),
                        ),
                    )
                    .order_by(Task.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        results.extend(
            _result(
                item.id,
                "task",
                item.title,
                item.description or item.priority,
                f"/tasks?task={item.id}",
                status=item.status,
            )
            for item in task_rows
        )

    if "workflow" in selected:
        workflow_rows = list(
            (
                await session.scalars(
                    select(Workflow)
                    .where(
                        Workflow.organization_id == actor.organization_id,
                        Workflow.status != "deleted",
                        or_(
                            Workflow.name.ilike(f"%{normalized}%"),
                            Workflow.description.ilike(f"%{normalized}%"),
                        ),
                    )
                    .order_by(Workflow.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        results.extend(
            _result(
                item.id,
                "workflow",
                item.name,
                item.description or item.trigger,
                f"/workflows?workflow={item.id}",
                status=item.status,
            )
            for item in workflow_rows
        )

    if "report" in selected:
        report_rows = list(
            (
                await session.scalars(
                    select(Report)
                    .where(
                        Report.organization_id == actor.organization_id,
                        or_(
                            Report.name.ilike(f"%{normalized}%"),
                            Report.summary.ilike(f"%{normalized}%"),
                        ),
                    )
                    .order_by(Report.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        results.extend(
            _result(
                item.id,
                "report",
                item.name,
                item.summary or item.type,
                f"/reports?report={item.id}",
                status=item.status,
            )
            for item in report_rows
        )

    if "knowledge" in selected:
        knowledge_rows = list(
            (
                await session.scalars(
                    select(KnowledgeItem)
                    .where(
                        KnowledgeItem.organization_id == actor.organization_id,
                        KnowledgeItem.status == "verified",
                        or_(
                            KnowledgeItem.subject.ilike(f"%{normalized}%"),
                            KnowledgeItem.content_text.ilike(f"%{normalized}%"),
                            KnowledgeItem.namespace.ilike(f"%{normalized}%"),
                        ),
                        (KnowledgeItem.scope_type != "user")
                        | (KnowledgeItem.scope_id == actor.id),
                    )
                    .order_by(KnowledgeItem.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        results.extend(
            _result(
                item.id,
                "knowledge",
                item.subject,
                item.content_text[:240],
                f"/knowledge?item={item.id}",
                status=item.status,
            )
            for item in knowledge_rows
        )

    if "lesson" in selected:
        lesson_rows = list(
            (
                await session.scalars(
                    select(Lesson)
                    .where(
                        Lesson.organization_id == actor.organization_id,
                        Lesson.status == "verified",
                        or_(
                            Lesson.title.ilike(f"%{normalized}%"),
                            Lesson.lesson.ilike(f"%{normalized}%"),
                        ),
                    )
                    .order_by(Lesson.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        results.extend(
            _result(
                item.id,
                "lesson",
                item.title,
                item.lesson[:240],
                f"/knowledge?lesson={item.id}",
                status=item.status,
            )
            for item in lesson_rows
        )

    if "workforce" in selected and (
        "*" in actor.permissions or "workforce:read" in actor.permissions
    ):
        workforce_rows = list(
            (
                await session.scalars(
                    select(WorkforceMember)
                    .where(
                        WorkforceMember.organization_id == actor.organization_id,
                        or_(
                            WorkforceMember.name.ilike(f"%{normalized}%"),
                            WorkforceMember.role.ilike(f"%{normalized}%"),
                            WorkforceMember.department.ilike(f"%{normalized}%"),
                        ),
                    )
                    .order_by(WorkforceMember.updated_at.desc())
                    .limit(limit)
                )
            ).all()
        )
        results.extend(
            _result(
                item.id,
                "workforce",
                item.name,
                f"{item.role} · {item.department}",
                f"/owner/staff?member={item.id}",
                status=item.status,
            )
            for item in workforce_rows
        )

    ordered = results[:limit]
    return {
        "query": normalized,
        "type": type,
        "total": len(results),
        "results": ordered,
        "provider_claims": False,
    }
