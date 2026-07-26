"""Meeting endpoints backed by the consolidated runtime store."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.auth import UserRecord, current_user
from app.core.runtime_store import new_id, runtime_store, utcnow

router = APIRouter()


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


def _visible(user: UserRecord):
    return [item for item in runtime_store.meetings.values() if not item.get("deleted") and item.get("organization_id") == user.organization_id]


@router.get("")
async def list_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    project_id: Optional[str] = None,
    user: UserRecord = Depends(current_user),
):
    meetings = _visible(user)
    if status_filter:
        meetings = [item for item in meetings if item.get("status") == status_filter]
    if project_id:
        meetings = [item for item in meetings if item.get("project_id") == project_id]
    meetings.sort(key=lambda item: item.get("start_time", ""), reverse=True)
    return meetings[skip : skip + limit]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_meeting(data: MeetingCreate, user: UserRecord = Depends(current_user)):
    if data.project_id:
        project = runtime_store.projects.get(data.project_id)
        if not project or project.get("deleted") or project.get("organization_id") != user.organization_id:
            raise HTTPException(status_code=404, detail="Project not found")
    is_owner = user.role in {"Super Owner", "Owner"} or "*" in user.permissions
    meeting_id = new_id("meeting")
    meeting = {
        "id": meeting_id,
        "title": data.title.strip(),
        "description": data.description,
        "status": "scheduled" if is_owner else "pending_approval",
        "organization_id": user.organization_id,
        "workspace_id": data.workspace_id,
        "project_id": data.project_id,
        "organizer_id": user.id,
        "organizer": user.name,
        "attendee_ids": list(dict.fromkeys([user.id, *data.attendee_ids])),
        "start_time": data.start_time.isoformat(),
        "end_time": data.end_time.isoformat() if data.end_time else None,
        "location": data.location,
        "approved_by_owner": is_owner,
        "created_at": utcnow(),
        "updated_at": utcnow(),
        "deleted": False,
    }
    runtime_store.meetings[meeting_id] = meeting
    runtime_store.add_activity("meeting", "Meeting created", meeting["title"], user.id)
    return meeting


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: str, user: UserRecord = Depends(current_user)):
    meeting = runtime_store.meetings.get(meeting_id)
    if not meeting or meeting.get("deleted") or meeting.get("organization_id") != user.organization_id:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.put("/{meeting_id}")
async def update_meeting(meeting_id: str, data: MeetingUpdate, user: UserRecord = Depends(current_user)):
    meeting = await get_meeting(meeting_id, user)
    source = runtime_store.meetings[meeting_id]
    updates = data.model_dump(exclude_unset=True)
    if "approved_by_owner" in updates and updates["approved_by_owner"] and not (user.role in {"Super Owner", "Owner"} or "*" in user.permissions):
        raise HTTPException(status_code=403, detail="Owner approval required")
    for key in ("start_time", "end_time"):
        if key in updates and updates[key] is not None:
            updates[key] = updates[key].isoformat()
    if updates.get("approved_by_owner"):
        updates["status"] = "scheduled"
    source.update(updates)
    source["updated_at"] = utcnow()
    runtime_store.add_activity("meeting", "Meeting updated", source["title"], user.id)
    return source


@router.delete("/{meeting_id}")
async def delete_meeting(meeting_id: str, user: UserRecord = Depends(current_user)):
    await get_meeting(meeting_id, user)
    runtime_store.meetings[meeting_id]["deleted"] = True
    runtime_store.meetings[meeting_id]["updated_at"] = utcnow()
    return {"message": "Meeting deleted successfully"}
