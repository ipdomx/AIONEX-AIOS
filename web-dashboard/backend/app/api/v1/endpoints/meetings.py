"""Organization-scoped meeting endpoints backed by the relational database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Optional

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import AuditEvent, Meeting, Project, User, Workspace
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _can_approve(actor: UserRecord) -> bool:
    return (
        actor.role in {"Super Owner", "Owner"}
        or "*" in actor.permissions
        or "meetings:approve" in actor.permissions
    )


def _serialize(meeting: Meeting, organizer_name: str) -> dict[str, Any]:
    return {
        "id": meeting.id,
        "title": meeting.title,
        "description": meeting.description,
        "status": meeting.status,
        "organization_id": meeting.organization_id,
        "workspace_id": meeting.workspace_id,
        "project_id": meeting.project_id,
        "organizer_id": meeting.organizer_id,
        "organizer": organizer_name,
        "attendee_ids": meeting.attendee_ids or [meeting.organizer_id],
        "start_time": _iso(meeting.start_time),
        "end_time": _iso(meeting.end_time),
        "location": meeting.location,
        "approved_by_owner": meeting.approved_by_id is not None,
        "approved_by_id": meeting.approved_by_id,
        "approved_at": _iso(meeting.approved_at),
        "created_at": _iso(meeting.created_at),
        "updated_at": _iso(meeting.updated_at),
        "deleted": meeting.status == "deleted",
    }


async def _meeting_row(
    session: AsyncSession,
    meeting_id: str,
    organization_id: str,
    *,
    for_update: bool = False,
):
    statement = (
        select(Meeting, User.name)
        .join(User, User.id == Meeting.organizer_id)
        .where(
            Meeting.id == meeting_id,
            Meeting.organization_id == organization_id,
            Meeting.status != "deleted",
        )
    )
    if for_update:
        statement = statement.with_for_update()
    return (await session.execute(statement)).one_or_none()


async def _validated_attendees(
    session: AsyncSession,
    actor: UserRecord,
    attendee_ids: list[str],
    *,
    required_id: str | None = None,
) -> list[str]:
    unique_ids = list(dict.fromkeys([required_id or actor.id, *attendee_ids]))
    existing = set(
        (
            await session.scalars(
                select(User.id).where(
                    User.id.in_(unique_ids),
                    User.organization_id == actor.organization_id,
                    User.deleted_at.is_(None),
                )
            )
        ).all()
    )
    if existing != set(unique_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more meeting attendees were not found",
        )
    return unique_ids


def _audit(
    actor: UserRecord,
    action: str,
    meeting: Meeting,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent(
        organization_id=actor.organization_id,
        user_id=actor.id,
        action=action,
        resource_type="meeting",
        resource_id=meeting.id,
        details={"title": meeting.title, **(details or {})},
    )


class MeetingCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    description: Optional[str] = None
    workspace_id: Optional[str] = None
    project_id: Optional[str] = None
    attendee_ids: list[str] = Field(default_factory=list)
    start_time: datetime
    end_time: Optional[datetime] = None
    location: Optional[str] = None


class MeetingUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=2, max_length=180)
    description: Optional[str] = None
    status: Optional[str] = None
    attendee_ids: Optional[list[str]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = None
    approved_by_owner: Optional[bool] = None


@router.get("")
async def list_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    project_id: Optional[str] = None,
    actor: UserRecord = Depends(require_permissions("meetings:read")),
    session: AsyncSession = Depends(get_db),
):
    statement = (
        select(Meeting, User.name)
        .join(User, User.id == Meeting.organizer_id)
        .where(
            Meeting.organization_id == actor.organization_id,
            Meeting.status != "deleted",
        )
    )
    if status_filter:
        statement = statement.where(Meeting.status == status_filter)
    if project_id:
        statement = statement.where(Meeting.project_id == project_id)
    rows = (
        await session.execute(
            statement.order_by(Meeting.start_time.desc()).offset(skip).limit(limit)
        )
    ).all()
    return [_serialize(meeting, organizer_name) for meeting, organizer_name in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_meeting(
    data: MeetingCreate,
    actor: UserRecord = Depends(require_permissions("meetings:write")),
    session: AsyncSession = Depends(get_db),
):
    if data.end_time is not None and _as_utc(data.end_time) <= _as_utc(data.start_time):
        raise HTTPException(
            status_code=422,
            detail="Meeting end time must be after its start time",
        )
    project: Project | None = None
    if data.project_id:
        project = await session.scalar(
            select(Project).where(
                Project.id == data.project_id,
                Project.organization_id == actor.organization_id,
                Project.status != "deleted",
            )
        )
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        if data.workspace_id and data.workspace_id != project.workspace_id:
            raise HTTPException(
                status_code=422,
                detail="Meeting workspace does not match the selected project",
            )
    workspace_id = data.workspace_id or (project.workspace_id if project else None)
    if workspace_id:
        workspace = await session.scalar(
            select(Workspace.id).where(
                Workspace.id == workspace_id,
                Workspace.organization_id == actor.organization_id,
                Workspace.status != "deleted",
            )
        )
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")
    attendees = await _validated_attendees(session, actor, data.attendee_ids)
    approved = _can_approve(actor)
    meeting = Meeting(
        organization_id=actor.organization_id,
        workspace_id=workspace_id,
        project_id=data.project_id,
        organizer_id=actor.id,
        approved_by_id=actor.id if approved else None,
        title=data.title.strip(),
        description=data.description,
        status="scheduled" if approved else "pending_approval",
        attendee_ids=attendees,
        start_time=data.start_time,
        end_time=data.end_time,
        location=data.location,
        approved_at=datetime.now(UTC) if approved else None,
    )
    session.add(meeting)
    await session.flush()
    session.add(_audit(actor, "meeting.create", meeting))
    await session.commit()
    row = await _meeting_row(session, meeting.id, actor.organization_id)
    if row is None:
        raise HTTPException(
            status_code=500, detail="Created meeting could not be loaded"
        )
    return _serialize(*row)


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: str,
    actor: UserRecord = Depends(require_permissions("meetings:read")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return _serialize(*row)


@router.put("/{meeting_id}")
async def update_meeting(
    meeting_id: str,
    data: MeetingUpdate,
    actor: UserRecord = Depends(require_permissions("meetings:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(
        session,
        meeting_id,
        actor.organization_id,
        for_update=True,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = row[0]
    updates = data.model_dump(exclude_unset=True)
    for field in ("title", "status", "start_time"):
        if field in updates and updates[field] is None:
            raise HTTPException(
                status_code=422,
                detail=f"Meeting {field} cannot be null",
            )
    if updates.get("status") == "deleted":
        raise HTTPException(
            status_code=422,
            detail="Use the delete endpoint to delete a meeting",
        )
    updated_start = updates.get("start_time", meeting.start_time)
    updated_end = updates.get("end_time", meeting.end_time)
    if updated_end is not None and _as_utc(updated_end) <= _as_utc(updated_start):
        raise HTTPException(
            status_code=422,
            detail="Meeting end time must be after its start time",
        )
    requested_approval = updates.pop("approved_by_owner", None)
    requested_status = updates.get("status")
    if (
        requested_approval is not None
        or requested_status in {"approved", "scheduled", "rejected"}
    ) and not _can_approve(actor):
        raise HTTPException(status_code=403, detail="Owner approval required")
    if "attendee_ids" in updates:
        meeting.attendee_ids = await _validated_attendees(
            session,
            actor,
            updates.pop("attendee_ids") or [],
            required_id=meeting.organizer_id,
        )
    if "title" in updates:
        updates["title"] = updates["title"].strip()
    for field in (
        "title",
        "description",
        "status",
        "start_time",
        "end_time",
        "location",
    ):
        if field in updates:
            setattr(meeting, field, updates[field])
    if requested_approval is True:
        meeting.approved_by_id = actor.id
        meeting.approved_at = datetime.now(UTC)
        meeting.status = "scheduled"
    elif requested_approval is False:
        meeting.approved_by_id = None
        meeting.approved_at = None
        if meeting.status == "scheduled":
            meeting.status = "pending_approval"
    session.add(
        _audit(
            actor,
            "meeting.update",
            meeting,
            {"fields": sorted(data.model_fields_set)},
        )
    )
    await session.commit()
    refreshed = await _meeting_row(session, meeting.id, actor.organization_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return _serialize(*refreshed)


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: str,
    actor: UserRecord = Depends(require_permissions("meetings:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(
        session,
        meeting_id,
        actor.organization_id,
        for_update=True,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = row[0]
    meeting.status = "deleted"
    session.add(_audit(actor, "meeting.delete", meeting))
    await session.commit()
    return {"message": "Meeting deleted successfully"}
