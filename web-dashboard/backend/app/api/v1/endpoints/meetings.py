"""Durable organization meetings, attendance, minutes, and approval lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.core.auth import UserRecord, require_permissions
from app.db.base import get_db
from app.db.models import (
    ApprovalRequest,
    AuditEvent,
    Meeting,
    MeetingAttendance,
    MeetingMinutes,
    Project,
    User,
    Workspace,
)
from app.services import communications, governance
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


def _iso(value: datetime | None) -> str | None:
    return governance.iso(value)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _can_approve(actor: UserRecord) -> bool:
    return (
        actor.role in {"Super Owner", "Owner"}
        or "*" in actor.permissions
        or "meetings:approve" in actor.permissions
        or "approvals:decide" in actor.permissions
    )


def _can_manage(meeting: Meeting, actor: UserRecord) -> bool:
    return meeting.organizer_id == actor.id or _can_approve(actor)


def _serialize(meeting: Meeting, organizer_name: str) -> dict[str, Any]:
    return {
        "id": meeting.id,
        "title": meeting.title,
        "description": meeting.description,
        "status": meeting.status,
        "meeting_type": meeting.meeting_type,
        "timezone": meeting.timezone,
        "agenda": meeting.agenda,
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
        "completed_at": _iso(meeting.completed_at),
        "cancel_reason": meeting.cancel_reason,
        "version": meeting.version,
        "created_at": _iso(meeting.created_at),
        "updated_at": _iso(meeting.updated_at),
        "deleted": meeting.status == "deleted",
    }


async def _serialize_full(
    session: AsyncSession, meeting: Meeting, organizer_name: str
) -> dict[str, Any]:
    attendance = list(
        (
            await session.scalars(
                select(MeetingAttendance)
                .where(MeetingAttendance.meeting_id == meeting.id)
                .order_by(MeetingAttendance.created_at)
            )
        ).all()
    )
    minutes = await session.scalar(
        select(MeetingMinutes).where(MeetingMinutes.meeting_id == meeting.id)
    )
    approval = await session.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.organization_id == meeting.organization_id,
            ApprovalRequest.target_type == "meeting",
            ApprovalRequest.target_id == meeting.id,
        )
        .order_by(ApprovalRequest.created_at.desc())
    )
    return {
        **_serialize(meeting, organizer_name),
        "attendance": [governance.attendance_snapshot(item) for item in attendance],
        "minutes": governance.minutes_snapshot(minutes) if minutes else None,
        "approval": governance.approval_snapshot(approval) if approval else None,
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
    description: str | None = Field(default=None, max_length=20000)
    workspace_id: str | None = None
    project_id: str | None = None
    attendee_ids: list[str] = Field(default_factory=list)
    start_time: datetime
    end_time: datetime | None = None
    location: str | None = Field(default=None, max_length=500)
    meeting_type: Literal["standard", "council", "ministry", "approval", "incident"] = "standard"
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    agenda: list[dict[str, Any]] = Field(default_factory=list)


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=20000)
    attendee_ids: list[str] | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    location: str | None = Field(default=None, max_length=500)
    meeting_type: Literal["standard", "council", "ministry", "approval", "incident"] | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    agenda: list[dict[str, Any]] | None = None
    approved_by_owner: bool | None = None
    approval_reason: str = Field(default="", max_length=2000)


class MeetingResponse(BaseModel):
    response_status: Literal["accepted", "declined", "tentative"]
    note: str | None = Field(default=None, max_length=2000)


class MeetingMinutesUpdate(BaseModel):
    summary: str | None = Field(default=None, max_length=20000)
    notes: str | None = Field(default=None, max_length=100000)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    action_items: list[dict[str, Any]] = Field(default_factory=list)
    publish: bool = False


class MeetingCancel(BaseModel):
    reason: str = Field(min_length=2, max_length=2000)


class MeetingResubmit(BaseModel):
    description: str | None = Field(default=None, max_length=10000)


@router.get("")
async def list_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    project_id: str | None = None,
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
        meeting_type=data.meeting_type,
        timezone=data.timezone,
        agenda=data.agenda,
        approved_at=datetime.now(UTC) if approved else None,
        version=1,
    )
    session.add(meeting)
    await session.flush()
    notifications = []
    attendance = await governance.ensure_meeting_attendance(
        session, meeting, attendees, actor_id=actor.id
    )
    if not approved:
        _approval, approval_notifications = await governance.create_approval_request(
            session,
            actor,
            target_type="meeting",
            target_id=meeting.id,
            title=f"Approve meeting: {meeting.title}",
            description=meeting.description,
            priority="high" if meeting.meeting_type in {"council", "ministry", "incident"} else "medium",
            risk="high" if meeting.meeting_type in {"incident", "ministry"} else "medium",
            metadata={
                "meeting_type": meeting.meeting_type,
                "start_time": _iso(meeting.start_time),
                "attendees": len(attendance),
            },
        )
        notifications.extend(approval_notifications)
    session.add(_audit(actor, "meeting.create", meeting, {"approval_required": not approved}))
    await session.commit()
    await communications.publish_many(notifications)
    row = await _meeting_row(session, meeting.id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=500, detail="Created meeting could not be loaded")
    return await _serialize_full(session, *row)


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: str,
    actor: UserRecord = Depends(require_permissions("meetings:read")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return await _serialize_full(session, *row)


@router.put("/{meeting_id}")
async def update_meeting(
    meeting_id: str,
    data: MeetingUpdate,
    actor: UserRecord = Depends(require_permissions("meetings:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id, for_update=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = row[0]
    if not _can_manage(meeting, actor):
        raise HTTPException(status_code=403, detail="Only the organizer or owner can update this meeting")
    updates = data.model_dump(exclude_unset=True)
    requested_approval = updates.pop("approved_by_owner", None)
    approval_reason = str(updates.pop("approval_reason", ""))
    updated_start = updates.get("start_time", meeting.start_time)
    updated_end = updates.get("end_time", meeting.end_time)
    if updated_start is None:
        raise HTTPException(status_code=422, detail="Meeting start_time cannot be null")
    if updated_end is not None and _as_utc(updated_end) <= _as_utc(updated_start):
        raise HTTPException(status_code=422, detail="Meeting end time must be after its start time")
    notifications = []
    if "attendee_ids" in updates:
        meeting.attendee_ids = await _validated_attendees(
            session,
            actor,
            updates.pop("attendee_ids") or [],
            required_id=meeting.organizer_id,
        )
        await governance.ensure_meeting_attendance(
            session, meeting, meeting.attendee_ids, actor_id=actor.id
        )
    if "title" in updates and updates["title"] is not None:
        updates["title"] = updates["title"].strip()
    for field in (
        "title",
        "description",
        "start_time",
        "end_time",
        "location",
        "meeting_type",
        "timezone",
        "agenda",
    ):
        if field in updates:
            setattr(meeting, field, updates[field])
    material_fields = {
        "title",
        "description",
        "start_time",
        "end_time",
        "location",
        "meeting_type",
        "attendee_ids",
        "agenda",
    }
    if material_fields.intersection(data.model_fields_set) and not _can_approve(actor):
        meeting.status = "pending_approval"
        meeting.approved_by_id = None
        meeting.approved_at = None
        approval, approval_notifications = await governance.create_approval_request(
            session,
            actor,
            target_type="meeting",
            target_id=meeting.id,
            title=f"Review revised meeting: {meeting.title}",
            description=meeting.description,
            priority="medium",
            risk="medium",
            metadata={"meeting_version": meeting.version + 1},
        )
        if approval.status == "changes_requested":
            approval, approval_notifications = await governance.resubmit_approval(
                session, actor, approval, description=meeting.description
            )
        notifications.extend(approval_notifications)
    if requested_approval is not None:
        if not _can_approve(actor):
            raise HTTPException(status_code=403, detail="Owner approval required")
        approval_to_decide = await session.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.organization_id == actor.organization_id,
                ApprovalRequest.target_type == "meeting",
                ApprovalRequest.target_id == meeting.id,
                ApprovalRequest.status.in_({"pending", "changes_requested"}),
            )
            .order_by(ApprovalRequest.created_at.desc())
        )
        if approval_to_decide is None:
            approval_to_decide, created_notifications = await governance.create_approval_request(
                session,
                actor,
                target_type="meeting",
                target_id=meeting.id,
                title=f"Approve meeting: {meeting.title}",
                description=meeting.description,
            )
            notifications.extend(created_notifications)
        approval_to_decide, _record, decision_notifications = await governance.decide_approval(
            session,
            actor,
            approval_to_decide,
            decision="approved" if requested_approval else "changes_requested",
            reason=approval_reason,
        )
        notifications.extend(decision_notifications)
    meeting.version += 1
    session.add(_audit(actor, "meeting.update", meeting, {"fields": sorted(data.model_fields_set)}))
    await session.commit()
    await communications.publish_many(notifications)
    refreshed = await _meeting_row(session, meeting.id, actor.organization_id)
    if refreshed is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return await _serialize_full(session, *refreshed)


@router.post("/{meeting_id}/respond")
async def respond_to_meeting(
    meeting_id: str,
    data: MeetingResponse,
    actor: UserRecord = Depends(require_permissions("meetings:read")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    try:
        attendance = await governance.respond_to_meeting(
            session,
            actor,
            row[0],
            response_status=data.response_status,
            note=data.note,
        )
        await session.commit()
    except PermissionError as exc:
        await session.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return governance.attendance_snapshot(attendance)


@router.get("/{meeting_id}/minutes")
async def get_minutes(
    meeting_id: str,
    actor: UserRecord = Depends(require_permissions("meetings:read")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    item = await session.scalar(
        select(MeetingMinutes).where(MeetingMinutes.meeting_id == meeting_id)
    )
    return governance.minutes_snapshot(item) if item else None


@router.put("/{meeting_id}/minutes")
async def update_minutes(
    meeting_id: str,
    data: MeetingMinutesUpdate,
    actor: UserRecord = Depends(require_permissions("meetings:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = row[0]
    if not _can_manage(meeting, actor):
        raise HTTPException(status_code=403, detail="Only the organizer or owner can manage minutes")
    item = await governance.upsert_minutes(
        session,
        actor,
        meeting,
        summary=data.summary,
        notes=data.notes,
        decisions=data.decisions,
        action_items=data.action_items,
        publish=data.publish,
    )
    await session.commit()
    return governance.minutes_snapshot(item)


@router.post("/{meeting_id}/complete")
async def complete_meeting(
    meeting_id: str,
    actor: UserRecord = Depends(require_permissions("meetings:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not _can_manage(row[0], actor):
        raise HTTPException(status_code=403, detail="Only the organizer or owner can complete the meeting")
    try:
        meeting = await governance.complete_meeting(session, actor, row[0])
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _serialize(meeting, row[1])


@router.post("/{meeting_id}/resubmit")
async def resubmit_meeting(
    meeting_id: str,
    data: MeetingResubmit,
    actor: UserRecord = Depends(require_permissions("meetings:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = row[0]
    if meeting.organizer_id != actor.id and not _can_approve(actor):
        raise HTTPException(status_code=403, detail="Only the organizer can resubmit this meeting")
    approval = await session.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.organization_id == actor.organization_id,
            ApprovalRequest.target_type == "meeting",
            ApprovalRequest.target_id == meeting.id,
        )
        .order_by(ApprovalRequest.created_at.desc())
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="Meeting approval request not found")
    try:
        approval, notifications = await governance.resubmit_approval(
            session, actor, approval, description=data.description or meeting.description
        )
        meeting.status = "pending_approval"
        meeting.version += 1
        await session.commit()
    except (LookupError, ValueError) as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await communications.publish_many(notifications)
    return {
        "meeting": _serialize(meeting, row[1]),
        "approval": governance.approval_snapshot(approval),
    }


@router.post("/{meeting_id}/cancel")
async def cancel_meeting(
    meeting_id: str,
    data: MeetingCancel,
    actor: UserRecord = Depends(require_permissions("meetings:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id, for_update=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = row[0]
    if not _can_manage(meeting, actor):
        raise HTTPException(status_code=403, detail="Only the organizer or owner can cancel this meeting")
    if meeting.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Meeting is already terminal")
    meeting.status = "cancelled"
    meeting.cancel_reason = data.reason.strip()
    meeting.version += 1
    session.add(_audit(actor, "meeting.cancelled", meeting, {"reason": data.reason.strip()}))
    await session.commit()
    return _serialize(meeting, row[1])


@router.delete("/{meeting_id}")
async def delete_meeting(
    meeting_id: str,
    actor: UserRecord = Depends(require_permissions("meetings:write")),
    session: AsyncSession = Depends(get_db),
):
    row = await _meeting_row(session, meeting_id, actor.organization_id, for_update=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    meeting = row[0]
    if not _can_manage(meeting, actor):
        raise HTTPException(status_code=403, detail="Only the organizer or owner can delete this meeting")
    meeting.status = "deleted"
    meeting.version += 1
    session.add(_audit(actor, "meeting.delete", meeting))
    await session.commit()
    return {"message": "Meeting deleted successfully"}
